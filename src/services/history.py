"""In-memory conversation history with a 20-message context window."""

import asyncio
import logging
from typing import TYPE_CHECKING

from pydantic_core import to_jsonable_python

from pydantic_ai import ModelMessagesTypeAdapter

if TYPE_CHECKING:
    from pydantic_ai import ModelMessage

logger = logging.getLogger(__name__)

CONTEXT_WINDOW_SIZE = 20


class HistoryService:
    """Store and retrieve Pydantic AI message history per user in memory."""

    def __init__(self) -> None:
        self._store: dict[int, list] = {}
        self._lock = asyncio.Lock()

    async def get(self, user_id: int) -> list["ModelMessage"]:
        """Load up to the last 20 messages for the user (oldest to newest)."""
        async with self._lock:
            raw = self._store.get(user_id)
        if not raw:
            return []
        try:
            return ModelMessagesTypeAdapter.validate_python(raw)
        except Exception as e:
            logger.warning("Failed to load history for user %s: %s", user_id, e)
            return []

    async def append(self, user_id: int, new_messages: list["ModelMessage"]) -> None:
        """Append new messages and keep only the last CONTEXT_WINDOW_SIZE messages."""
        if not new_messages:
            return
        async with self._lock:
            existing = self._store.get(user_id) or []
            combined = existing + to_jsonable_python(new_messages)
            trimmed = combined[-CONTEXT_WINDOW_SIZE:]
            self._store[user_id] = trimmed
        logger.debug("Saved %d messages for user %s (window=%d)", len(trimmed), user_id, CONTEXT_WINDOW_SIZE)
