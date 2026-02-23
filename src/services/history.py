"""Redis-backed conversation history with a 20-message context window."""

import json
import logging
from typing import TYPE_CHECKING

from pydantic_core import to_jsonable_python

from pydantic_ai import ModelMessagesTypeAdapter

if TYPE_CHECKING:
    from pydantic_ai import ModelMessage
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

CONTEXT_WINDOW_SIZE = 20
KEY_PREFIX = "chat:"


class HistoryService:
    """Store and retrieve Pydantic AI message history per user in Redis."""

    def __init__(self, redis: "Redis", key_prefix: str = KEY_PREFIX) -> None:
        self._redis = redis
        self._prefix = key_prefix

    def _key(self, user_id: int) -> str:
        return f"{self._prefix}{user_id}"

    async def get(self, user_id: int) -> list["ModelMessage"]:
        """Load up to the last 20 messages for the user (oldest to newest)."""
        key = self._key(user_id)
        raw = await self._redis.get(key)
        if not raw:
            return []
        try:
            data = json.loads(raw) if isinstance(raw, bytes) else raw
            return ModelMessagesTypeAdapter.validate_python(data)
        except Exception as e:
            logger.warning("Failed to load history for user %s: %s", user_id, e)
            return []

    async def append(self, user_id: int, new_messages: list["ModelMessage"]) -> None:
        """Append new messages and keep only the last CONTEXT_WINDOW_SIZE messages."""
        if not new_messages:
            return
        existing = await self.get(user_id)
        combined = existing + new_messages
        trimmed = combined[-CONTEXT_WINDOW_SIZE:]
        key = self._key(user_id)
        payload = to_jsonable_python(trimmed)
        await self._redis.set(key, json.dumps(payload))
        logger.debug("Saved %d messages for user %s (window=%d)", len(trimmed), user_id, CONTEXT_WINDOW_SIZE)
