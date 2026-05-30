"""Tests for OpenAI quota detection and user-facing transcription errors."""

import os
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("GOOGLE_API_KEY", "test-key")
from openai import APIError, RateLimitError

from src.errors import (
    OPENAI_QUOTA_EXHAUSTED_MESSAGE,
    UserFacingError,
    is_openai_insufficient_quota,
    openai_error_code,
)
from src.services.transcribe import TranscribeService
from src.telegram.models import Update
from src.webhook.handler import HandlerDeps, process_updates_batch


def _quota_api_error() -> APIError:
    request = MagicMock()
    response = MagicMock(status_code=429, headers={}, request=request)
    body = {
        "error": {
            "message": "You exceeded your current quota, please check your plan and billing details.",
            "type": "insufficient_quota",
            "param": None,
            "code": "insufficient_quota",
        }
    }
    return RateLimitError(
        message="Error code: 429 - insufficient_quota",
        response=response,
        body=body,
    )


def test_openai_error_code_reads_nested_error_payload() -> None:
    exc = _quota_api_error()
    assert openai_error_code(exc) == "insufficient_quota"
    assert is_openai_insufficient_quota(exc)


@pytest.mark.asyncio
async def test_transcribe_maps_insufficient_quota_to_user_facing_error() -> None:
    openai = AsyncMock()
    openai.audio.transcriptions.create = AsyncMock(side_effect=_quota_api_error())
    telegram = AsyncMock()
    telegram.get_file = AsyncMock(return_value={"file_path": "voice/file.ogg"})
    telegram.download_file = AsyncMock(return_value=b"ogg-bytes")

    service = TranscribeService(openai, telegram)

    with pytest.raises(UserFacingError) as exc_info:
        await service.transcribe_voice("file-id")

    assert exc_info.value.user_message == OPENAI_QUOTA_EXHAUSTED_MESSAGE


@pytest.mark.asyncio
async def test_handler_sends_quota_message_for_voice_updates() -> None:
    openai = AsyncMock()
    openai.audio.transcriptions.create = AsyncMock(side_effect=_quota_api_error())
    telegram = AsyncMock()
    telegram.get_file = AsyncMock(return_value={"file_path": "voice/file.ogg"})
    telegram.download_file = AsyncMock(return_value=b"ogg-bytes")
    telegram.send_message = AsyncMock(return_value={"ok": True})

    transcribe = TranscribeService(openai, telegram)
    deps = HandlerDeps(
        telegram=telegram,
        history=AsyncMock(get=AsyncMock(return_value=[]), append=AsyncMock()),
        transcribe=transcribe,
        agent=AsyncMock(),
        allowed_user_ids={123},
        google_api_key="fake",
    )

    update = Update.model_validate(
        {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "from": {"id": 123, "is_bot": False, "first_name": "U"},
                "chat": {"id": 456, "type": "private"},
                "date": 1_700_000_000,
                "voice": {"file_id": "voice-file", "duration": 3},
            },
        }
    )

    await process_updates_batch([update], deps)

    telegram.send_message.assert_awaited_once_with(456, OPENAI_QUOTA_EXHAUSTED_MESSAGE)
    deps.agent.run.assert_not_called()
