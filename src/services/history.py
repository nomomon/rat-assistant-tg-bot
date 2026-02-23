"""In-memory conversation history with a 1-hour time-based context window."""

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from pydantic_core import to_jsonable_python

from pydantic_ai import ModelMessagesTypeAdapter

if TYPE_CHECKING:
    from pydantic_ai import ModelMessage

logger = logging.getLogger(__name__)

CONTEXT_WINDOW_SECONDS = 3600


def _is_timestamped_entry(item: Any) -> bool:
    """True if item is a dict with 'ts' and 'm' (new format)."""
    return isinstance(item, dict) and "ts" in item and "m" in item


def _message_dict_from_entry(item: Any, cutoff: float) -> Any | None:
    """Extract message dict if entry is within the time window. None if legacy or too old."""
    if _is_timestamped_entry(item) and item["ts"] >= cutoff:
        return item["m"]
    return None


class HistoryService:
    """Store and retrieve Pydantic AI message history per user in memory."""

    def __init__(self) -> None:
        self._store: dict[int, list] = {}
        self._lock = asyncio.Lock()

    async def get(self, user_id: int) -> list["ModelMessage"]:
        """Load messages for the user from the last hour (oldest to newest)."""
        cutoff = time.time() - CONTEXT_WINDOW_SECONDS
        async with self._lock:
            raw = self._store.get(user_id)
        if not raw:
            return []
        extracted = []
        for item in raw:
            msg_dict = _message_dict_from_entry(item, cutoff)
            if msg_dict is not None:
                extracted.append(msg_dict)
        if not extracted:
            return []
        try:
            return ModelMessagesTypeAdapter.validate_python(extracted)
        except Exception as e:
            logger.warning("Failed to load history for user %s: %s", user_id, e)
            return []

    async def append(self, user_id: int, new_messages: list["ModelMessage"]) -> None:
        """Append new messages and keep only messages from the last hour."""
        if not new_messages:
            return
        now = time.time()
        cutoff = now - CONTEXT_WINDOW_SECONDS
        async with self._lock:
            existing = self._store.get(user_id) or []
            for msg in to_jsonable_python(new_messages):
                existing.append({"ts": now, "m": msg})
            trimmed = [
                entry
                for entry in existing
                if _is_timestamped_entry(entry) and entry["ts"] >= cutoff
            ]
            self._store[user_id] = trimmed
        logger.debug(
            "Saved %d messages for user %s (window=%ds)",
            len(trimmed),
            user_id,
            CONTEXT_WINDOW_SECONDS,
        )
