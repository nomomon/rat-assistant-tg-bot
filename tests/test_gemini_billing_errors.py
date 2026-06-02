"""Tests for Gemini billing detection and user-facing agent errors."""

import os
from unittest.mock import AsyncMock

import pytest

os.environ.setdefault("GOOGLE_API_KEY", "test-key")
from pydantic_ai.exceptions import ModelHTTPError

from src.errors import GEMINI_BILLING_MESSAGE, is_gemini_billing_error
from src.telegram.models import Update
from src.webhook.handler import HandlerDeps, process_updates_batch


def _gemini_billing_error() -> ModelHTTPError:
    return ModelHTTPError(
        status_code=403,
        model_name="gemini-3.1-pro-preview",
        body={
            "error": {
                "code": 403,
                "message": "Lightning dunning decision is deny for project: projects/1057855599036",
                "status": "PERMISSION_DENIED",
            }
        },
    )


def test_is_gemini_billing_error_detects_dunning_permission_denied() -> None:
    assert is_gemini_billing_error(_gemini_billing_error())


def test_is_gemini_billing_error_rejects_unrelated_errors() -> None:
    server_error = ModelHTTPError(
        status_code=500,
        model_name="gemini-3.1-pro-preview",
        body={"error": {"message": "Internal error", "status": "INTERNAL"}},
    )
    assert not is_gemini_billing_error(server_error)

    forbidden = ModelHTTPError(
        status_code=403,
        model_name="gemini-3.1-pro-preview",
        body={
            "error": {
                "code": 403,
                "message": "API key not valid. Please pass a valid API key.",
                "status": "INVALID_ARGUMENT",
            }
        },
    )
    assert not is_gemini_billing_error(forbidden)


@pytest.mark.asyncio
async def test_handler_sends_billing_message_for_gemini_agent_errors() -> None:
    agent = AsyncMock()
    agent.run = AsyncMock(side_effect=_gemini_billing_error())

    telegram = AsyncMock()
    telegram.send_message = AsyncMock(return_value={"ok": True})

    deps = HandlerDeps(
        telegram=telegram,
        history=AsyncMock(get=AsyncMock(return_value=[]), append=AsyncMock()),
        transcribe=AsyncMock(),
        agent=agent,
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
                "text": "Hello",
            },
        }
    )

    await process_updates_batch([update], deps)

    agent.run.assert_awaited_once()
    telegram.send_message.assert_awaited_once_with(456, GEMINI_BILLING_MESSAGE)
