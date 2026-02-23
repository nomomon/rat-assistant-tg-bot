"""Redis-backed conversation history with a 1-hour time-based context window."""

import json
import logging
import time
from typing import TYPE_CHECKING, Any

import redis.asyncio as redis
from pydantic_core import to_jsonable_python

from pydantic_ai import ModelMessagesTypeAdapter

if TYPE_CHECKING:
    from pydantic_ai import ModelMessage

logger = logging.getLogger(__name__)

CONTEXT_WINDOW_SECONDS = 3600
KEY_PREFIX = "chat:history:"


def _is_timestamped_entry(item: Any) -> bool:
    """True if item is a dict with 'ts' and 'm' (new format)."""
    return isinstance(item, dict) and "ts" in item and "m" in item


def _message_dict_from_entry(item: Any, cutoff: float) -> Any | None:
    """Extract message dict if entry is within the time window. None if legacy or too old."""
    if _is_timestamped_entry(item) and item["ts"] >= cutoff:
        return item["m"]
    return None


class HistoryService:
    """Store and retrieve Pydantic AI message history per user in Redis."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: redis.Redis | None = None

    async def _get_client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._client

    def _key(self, user_id: int) -> str:
        return f"{KEY_PREFIX}{user_id}"

    async def get(self, user_id: int) -> list["ModelMessage"]:
        """Load messages for the user from the last hour (oldest to newest)."""
        cutoff = time.time() - CONTEXT_WINDOW_SECONDS
        client = await self._get_client()
        key = self._key(user_id)
        raw_json = await client.get(key)
        if not raw_json:
            return []
        try:
            raw = json.loads(raw_json)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Invalid history data for user %s", user_id)
            return []
        if not isinstance(raw, list):
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
        client = await self._get_client()
        key = self._key(user_id)
        raw_json = await client.get(key)
        existing = []
        if raw_json:
            try:
                existing = json.loads(raw_json)
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, TypeError):
                existing = []
        for msg in to_jsonable_python(new_messages):
            existing.append({"ts": now, "m": msg})
        trimmed = [
            entry
            for entry in existing
            if _is_timestamped_entry(entry) and entry["ts"] >= cutoff
        ]
        await client.set(key, json.dumps(trimmed))
        logger.debug(
            "Saved %d messages for user %s (window=%ds)",
            len(trimmed),
            user_id,
            CONTEXT_WINDOW_SECONDS,
        )

    async def aclose(self) -> None:
        """Close the Redis connection (e.g. on app shutdown)."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
