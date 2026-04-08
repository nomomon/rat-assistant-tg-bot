"""Tests for webhook message coalescing and batched history behavior."""

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from src.telegram.models import Update
from src.webhook.handler import HandlerDeps, process_updates_batch


def _update_payload(update_id: int, text: str | None) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "from": {"id": 123, "is_bot": False, "first_name": "U"},
            "chat": {"id": 456, "type": "private"},
            "date": 1_700_000_000 + update_id,
            "text": text,
        },
    }


def _make_request(payload: dict) -> Request:
    body = json.dumps(payload).encode("utf-8")
    sent = {"done": False}

    async def receive() -> dict:
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/webhook",
        "raw_path": b"/webhook",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
    }
    return Request(scope, receive)


@pytest.mark.asyncio
async def test_webhook_coalesces_messages_within_window(monkeypatch):
    from src.main import create_app
    import src.main as main_module

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("GOOGLE_API_KEY", "x")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    app = create_app()
    app.state.settings.message_coalesce_window_seconds = 0.05
    app.state.telegram = AsyncMock()
    app.state.history = AsyncMock()
    app.state.transcribe = AsyncMock()
    app.state.agent = AsyncMock()

    route = next(r for r in app.routes if getattr(r, "path", None) == "/webhook")
    webhook = route.endpoint

    captured_batches: list[list[Update]] = []

    async def _fake_process_updates_batch(updates, deps):
        captured_batches.append(updates)

    monkeypatch.setattr(main_module, "process_updates_batch", _fake_process_updates_batch)

    await webhook(_make_request(_update_payload(1, "one")))
    await webhook(_make_request(_update_payload(2, "two")))
    await asyncio.sleep(0.09)

    assert len(captured_batches) == 1
    assert [u.message.text for u in captured_batches[0]] == ["one", "two"]


@pytest.mark.asyncio
async def test_webhook_splits_messages_outside_window(monkeypatch):
    from src.main import create_app
    import src.main as main_module

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("GOOGLE_API_KEY", "x")
    monkeypatch.setenv("ALLOWED_TELEGRAM_USER_IDS", "123")

    app = create_app()
    app.state.settings.message_coalesce_window_seconds = 0.04
    app.state.telegram = AsyncMock()
    app.state.history = AsyncMock()
    app.state.transcribe = AsyncMock()
    app.state.agent = AsyncMock()

    route = next(r for r in app.routes if getattr(r, "path", None) == "/webhook")
    webhook = route.endpoint

    captured_batches: list[list[Update]] = []

    async def _fake_process_updates_batch(updates, deps):
        captured_batches.append(updates)

    monkeypatch.setattr(main_module, "process_updates_batch", _fake_process_updates_batch)

    await webhook(_make_request(_update_payload(1, "one")))
    await asyncio.sleep(0.07)
    await webhook(_make_request(_update_payload(2, "two")))
    await asyncio.sleep(0.07)

    assert len(captured_batches) == 2
    assert [u.message.text for u in captured_batches[0]] == ["one"]
    assert [u.message.text for u in captured_batches[1]] == ["two"]


@pytest.mark.asyncio
async def test_batch_preserves_consecutive_user_turns_order():
    deps = HandlerDeps(
        telegram=AsyncMock(),
        history=AsyncMock(),
        transcribe=AsyncMock(),
        agent=AsyncMock(),
        allowed_user_ids={123},
        google_api_key="k",
    )
    deps.history.get = AsyncMock(return_value=[])
    deps.history.append = AsyncMock()
    deps.telegram.send_chat_action = AsyncMock()

    result = SimpleNamespace(new_messages=lambda: [])
    deps.agent.run = AsyncMock(return_value=result)

    updates = [
        Update.model_validate(_update_payload(1, "first")),
        Update.model_validate(_update_payload(2, "second")),
    ]
    await process_updates_batch(updates, deps)

    deps.agent.run.assert_awaited_once()
    args, kwargs = deps.agent.run.await_args
    assert args[0] == "second"
    history = kwargs["message_history"]
    assert len(history) == 1
    assert history[0].parts[0].content == "first"


@pytest.mark.asyncio
async def test_batch_skips_unsupported_messages_and_still_flushes():
    deps = HandlerDeps(
        telegram=AsyncMock(),
        history=AsyncMock(),
        transcribe=AsyncMock(),
        agent=AsyncMock(),
        allowed_user_ids={123},
        google_api_key="k",
    )
    deps.history.get = AsyncMock(return_value=[])
    deps.history.append = AsyncMock()
    deps.telegram.send_chat_action = AsyncMock()

    result = SimpleNamespace(new_messages=lambda: [])
    deps.agent.run = AsyncMock(return_value=result)

    unsupported = _update_payload(1, None)
    unsupported["message"].pop("text")
    supported = _update_payload(2, "works")

    await process_updates_batch(
        [Update.model_validate(unsupported), Update.model_validate(supported)],
        deps,
    )

    deps.agent.run.assert_awaited_once()
    args, kwargs = deps.agent.run.await_args
    assert args[0] == "works"
    assert kwargs["message_history"] is None
