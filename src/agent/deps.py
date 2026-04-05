"""Agent dependencies: Telegram client and target chat."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from src.telegram.client import TelegramClient


@dataclass
class AgentDeps:
    telegram_client: TelegramClient
    chat_id: int
    google_api_key: str
    begin_reply_chat_action: Callable[[bool], Awaitable[None]] | None = None
