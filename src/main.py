"""FastAPI app: webhook endpoint, lifespan for clients."""

import asyncio
import logging
from contextlib import asynccontextmanager

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
    """Create Telegram, OpenAI, in-memory history, agent; yield deps."""
    settings: Settings = app.state.settings
    telegram_client = TelegramClient(settings.telegram_bot_token)
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    history_service = HistoryService()
    transcribe_service = TranscribeService(openai_client, telegram_client)
    agent = create_agent()

    app.state.telegram = telegram_client
    app.state.history = history_service
    app.state.transcribe = transcribe_service
    app.state.agent = agent

    yield


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
        """Basic liveness check."""
        return {"status": "ok"}

    return app


app = create_app()
