"""Agent dependencies: Telegram client and target chat."""

from dataclasses import dataclass

from src.telegram.client import TelegramClient


@dataclass
class AgentDeps:
    telegram_client: TelegramClient
    chat_id: int
