"""Tests for chat-action lifecycle, message ordering, and voice action switching."""

import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Lightweight fakes so we can test tools.py / handler.py logic without a live
# Telegram API or Google Generative-AI credentials.
# ---------------------------------------------------------------------------

@dataclass
class _ActionLog:
    """Records every call to begin_reply_chat_action and the order of sends."""

    actions: list[str] = field(default_factory=list)
    sends: list[str] = field(default_factory=list)
    voice_sends: list[str] = field(default_factory=list)


def _make_begin_action(log: _ActionLog):
    """Return a coroutine that logs action switches."""

    async def begin(as_voice: bool) -> None:
        log.actions.append("record_voice" if as_voice else "typing")

    return begin


def _make_telegram_client(log: _ActionLog):
    """Return a mock TelegramClient that records sends."""

    client = AsyncMock()

    async def send_message(chat_id, text, *, parse_mode="markdown"):
        log.sends.append(text)
        return {"ok": True}

    async def send_voice(chat_id, voice, *, filename="reply.ogg", caption=None):
        log.voice_sends.append(caption or "")
        return {"ok": True}

    client.send_message = AsyncMock(side_effect=send_message)
    client.send_voice = AsyncMock(side_effect=send_voice)
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_send_does_not_restart_action():
    """send_message(as_voice=False) must NOT call begin_reply_chat_action.

    The typing action is started once by the handler before agent.run(); the
    tool should not restart it on every text send.
    """
    from src.agent.deps import AgentDeps

    log = _ActionLog()
    deps = AgentDeps(
        telegram_client=_make_telegram_client(log),
        chat_id=1,
        google_api_key="fake",
        begin_reply_chat_action=_make_begin_action(log),
        send_lock=asyncio.Lock(),
    )

    # Build a minimal RunContext mock
    ctx = MagicMock()
    ctx.deps = deps

    # Patch the import so we don't trigger real TTS/researcher
    from src.agent.tools import send_message

    await send_message(ctx, "Hello world")

    # begin_reply_chat_action should NOT have been called for a text send.
    assert log.actions == [], (
        f"Expected no action restarts for text send, got {log.actions}"
    )
    assert log.sends == ["Hello world"]


@pytest.mark.asyncio
async def test_voice_send_switches_to_record_voice():
    """send_message(as_voice=True) should switch to record_voice before audio
    generation and revert to typing afterwards.
    """
    from src.agent.deps import AgentDeps

    log = _ActionLog()
    deps = AgentDeps(
        telegram_client=_make_telegram_client(log),
        chat_id=1,
        google_api_key="fake",
        begin_reply_chat_action=_make_begin_action(log),
        send_lock=asyncio.Lock(),
    )
    ctx = MagicMock()
    ctx.deps = deps

    from src.agent.tools import send_message

    # Patch TTS to avoid real audio synthesis
    with patch("src.agent.tools.text_to_wav_file"), \
         patch("src.agent.tools.wav_bytes_to_ogg_opus", return_value=b"ogg"), \
         patch("tempfile.NamedTemporaryFile") as mock_tmp, \
         patch("pathlib.Path.read_bytes", return_value=b"wav"):
        mock_tmp.return_value.__enter__ = lambda s: MagicMock(name="/tmp/fake.wav")
        mock_tmp.return_value.__exit__ = lambda s, *a: None

        await send_message(ctx, "Voice reply", as_voice=True)

    # Should have switched to record_voice, then back to typing.
    assert log.actions == ["record_voice", "typing"], (
        f"Expected [record_voice, typing], got {log.actions}"
    )


@pytest.mark.asyncio
async def test_send_lock_serialises_concurrent_sends():
    """Multiple concurrent send_message calls must deliver messages in order."""
    from src.agent.deps import AgentDeps

    log = _ActionLog()
    lock = asyncio.Lock()
    deps = AgentDeps(
        telegram_client=_make_telegram_client(log),
        chat_id=1,
        google_api_key="fake",
        begin_reply_chat_action=_make_begin_action(log),
        send_lock=lock,
    )
    ctx = MagicMock()
    ctx.deps = deps

    from src.agent.tools import send_message

    # Fire three sends concurrently — they must arrive in FIFO order.
    await asyncio.gather(
        send_message(ctx, "first"),
        send_message(ctx, "second"),
        send_message(ctx, "third"),
    )

    assert log.sends == ["first", "second", "third"], (
        f"Expected ordered sends, got {log.sends}"
    )


@pytest.mark.asyncio
async def test_empty_text_skipped():
    """send_message with empty/whitespace text should be a no-op."""
    from src.agent.deps import AgentDeps

    log = _ActionLog()
    deps = AgentDeps(
        telegram_client=_make_telegram_client(log),
        chat_id=1,
        google_api_key="fake",
        begin_reply_chat_action=_make_begin_action(log),
        send_lock=asyncio.Lock(),
    )
    ctx = MagicMock()
    ctx.deps = deps

    from src.agent.tools import send_message

    await send_message(ctx, "   ")

    assert log.sends == []
    assert log.actions == []
