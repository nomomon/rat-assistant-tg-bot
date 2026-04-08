"""FastAPI app: webhook endpoint, lifespan for clients."""

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from fastapi import FastAPI, Request, Response
from openai import AsyncOpenAI

from src.config import Settings
from src.telegram.client import TelegramClient
from src.telegram.models import Update
from src.services.history import HistoryService
from src.services.transcribe import TranscribeService
from src.agent.agent import create_agent
from src.webhook.handler import process_update, process_updates_batch, HandlerDeps

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class _PendingBatch:
    """In-memory pending updates for one (chat_id, user_id) key."""

    updates: list[Update] = field(default_factory=list)
    flush_task: asyncio.Task[None] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create Telegram, OpenAI, Redis history, agent; yield deps."""
    settings: Settings = app.state.settings
    telegram_client = TelegramClient(settings.telegram_bot_token)
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    history_service = HistoryService(redis_url=settings.redis_url)
    transcribe_service = TranscribeService(openai_client, telegram_client)
    agent = create_agent()

    app.state.telegram = telegram_client
    app.state.history = history_service
    app.state.transcribe = transcribe_service
    app.state.agent = agent

    yield

    pending_batches = getattr(app.state, "pending_batches", {})
    for pending in pending_batches.values():
        if pending.flush_task is not None:
            pending.flush_task.cancel()
    for pending in pending_batches.values():
        if pending.flush_task is not None:
            try:
                await pending.flush_task
            except asyncio.CancelledError:
                pass
    pending_batches.clear()

    await history_service.aclose()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = Settings()
    app = FastAPI(title="Krysatich Bot", lifespan=lifespan)
    app.state.settings = settings
    app.state.pending_batches: dict[tuple[int, int], _PendingBatch] = {}
    app.state.pending_batches_lock = asyncio.Lock()

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
            google_api_key=settings.google_api_key,
        )

        if not update.message or update.user_id is None or update.chat_id is None:
            asyncio.create_task(process_update(update, deps))
            return Response(status_code=200)

        key = (update.chat_id, update.user_id)

        async def flush_after_window(batch_key: tuple[int, int], delay: float) -> None:
            try:
                await asyncio.sleep(delay)
                async with app.state.pending_batches_lock:
                    pending = app.state.pending_batches.get(batch_key)
                    if pending is None:
                        return
                    updates_to_process = pending.updates[:]
                    pending.updates.clear()
                    pending.flush_task = None
                    if not updates_to_process:
                        app.state.pending_batches.pop(batch_key, None)
                        return
                    app.state.pending_batches.pop(batch_key, None)
                await process_updates_batch(updates_to_process, deps)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Failed to flush coalesced updates for %s", batch_key)

        async with app.state.pending_batches_lock:
            pending = app.state.pending_batches.get(key)
            if pending is None:
                pending = _PendingBatch()
                app.state.pending_batches[key] = pending
            pending.updates.append(update)

            old_task = pending.flush_task
            if old_task is not None:
                old_task.cancel()
            pending.flush_task = asyncio.create_task(
                flush_after_window(key, settings.message_coalesce_window_seconds)
            )

        return Response(status_code=200)

    @app.get("/health")
    async def health() -> dict:
        """Basic liveness check."""
        return {"status": "ok"}

    return app


app = create_app()
