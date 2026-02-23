"""FastAPI app: webhook endpoint, lifespan for Redis and clients."""

import asyncio
import logging
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, Request, Response
from openai import AsyncOpenAI

from src.config import Settings
from src.telegram.client import TelegramClient
from src.telegram.models import Update
from src.services.history import HistoryService
from src.services.transcribe import TranscribeService
from src.agent.agent import create_agent
from src.webhook.handler import process_update, HandlerDeps

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create Redis, Telegram, OpenAI, agent; yield deps; close connections."""
    settings: Settings = app.state.settings
    redis_client = redis.from_url(settings.redis_url)
    telegram_client = TelegramClient(settings.telegram_bot_token)
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    history_service = HistoryService(redis_client)
    transcribe_service = TranscribeService(openai_client, telegram_client)
    agent = create_agent()

    app.state.redis = redis_client
    app.state.telegram = telegram_client
    app.state.history = history_service
    app.state.transcribe = transcribe_service
    app.state.agent = agent

    yield

    await redis_client.aclose()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = Settings()
    app = FastAPI(title="Krysatich Bot", lifespan=lifespan)
    app.state.settings = settings

    @app.post("/webhook")
    async def webhook(request: Request) -> Response:
        """Accept Telegram updates; return 200 immediately; process in background."""
        if settings.webhook_secret_token:
            secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if secret != settings.webhook_secret_token:
                return Response(status_code=403, content="Forbidden")

        body = await request.json()
        try:
            update = Update.model_validate(body)
        except Exception as e:
            logger.warning("Invalid update body: %s", e)
            return Response(status_code=200)

        deps = HandlerDeps(
            telegram=app.state.telegram,
            history=app.state.history,
            transcribe=app.state.transcribe,
            agent=app.state.agent,
            allowed_user_ids=settings.allowed_user_ids,
        )
        asyncio.create_task(process_update(update, deps))
        return Response(status_code=200)

    @app.get("/health")
    async def health() -> dict:
        """Check Redis connectivity."""
        try:
            r = app.state.redis
            await r.ping()
            return {"status": "ok", "redis": "ok"}
        except Exception as e:
            logger.warning("Health check failed: %s", e)
            return {"status": "error", "redis": str(e)}

    return app


app = create_app()
