"""Agent tools — functions the model can call during its turn."""

import asyncio
import logging
import os
import tempfile
from functools import partial
from pathlib import Path

from pydantic_ai import RunContext

from src.agent.deps import AgentDeps
from src.researcher.agent import researcher_agent
from src.tts import text_to_wav_file

logger = logging.getLogger(__name__)

TELEGRAM_MAX_LENGTH = 4096
TELEGRAM_CAPTION_MAX = 1024


def _split_message(text: str, limit: int = TELEGRAM_MAX_LENGTH) -> list[str]:
    """Split *text* into chunks that each fit within *limit* characters.

    Tries to break at paragraph boundaries first, then line breaks, then
    word boundaries, and finally falls back to a hard cut.
    """
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    while len(text) > limit:
        chunk = text[:limit]
        split_at = -1
        sep_len = 1
        for sep in ("\n\n", "\n", " "):
            idx = chunk.rfind(sep)
            if idx > 0:
                split_at = idx
                sep_len = len(sep)
                break

        if split_at > 0:
            parts.append(text[:split_at])
            text = text[split_at + sep_len:]
        else:
            parts.append(text[:limit])
            text = text[limit:]

    if text:
        parts.append(text)

    return parts


async def _send_text_chunks(ctx: RunContext[AgentDeps], text: str) -> None:
    chunks = _split_message(text)
    for chunk in chunks:
        try:
            await ctx.deps.telegram_client.send_message(ctx.deps.chat_id, chunk)
        except Exception:
            logger.warning(
                "send_message: markdown parse failed, retrying as plain text"
            )
            await ctx.deps.telegram_client.send_message(
                ctx.deps.chat_id, chunk, parse_mode=None
            )


async def research(ctx: RunContext[AgentDeps], query: str) -> str:
    """Research a topic on the web and return a detailed report.

    Use this tool whenever the user's question requires current or factual
    information from the internet — for example: recent news, definitions,
    how-to instructions, biographical facts, scientific data, or anything
    you are not certain about.

    Write the query as a thorough briefing for the researcher:
    - State exactly what information is needed
    - Describe the user's goal and context
    - Specify the required level of detail (e.g. brief summary vs. full explanation)

    The researcher will search the web and return a structured report with sources.
    Use that report to compose your reply via `send_message`.

    Args:
        query: Detailed description of what to research and why.

    Returns:
        A research report as plain text, including sources.
    """
    result = await researcher_agent.run(query)
    return result.output


async def send_message(
    ctx: RunContext[AgentDeps],
    text: str,
    *,
    as_voice: bool = False,
) -> None:
    """Send a reply to the user. Always call this tool to deliver your response.

    Long messages are split automatically at paragraph or line boundaries so
    each chunk stays within Telegram's 4 096-character limit.

    Set *as_voice* to True when a spoken reply fits best — for example the user
    asked for voice, prefers listening, or you want to improve accessibility.
    In that case the reply is sent as an audio attachment (with a short caption);
    if synthesis or upload fails, the reply is sent as plain text instead.

    Args:
        text: The full response text to send to the user.
        as_voice: If True, synthesize speech and send as Telegram audio; default False.
    """
    if not text.strip():
        logger.warning("send_message called with empty text — skipping")
        return

    begin = ctx.deps.begin_reply_chat_action
    if begin is not None:
        await begin(as_voice)

    if not as_voice:
        await _send_text_chunks(ctx, text)
        return

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        await asyncio.to_thread(
            partial(
                text_to_wav_file,
                text.strip(),
                Path(tmp_path),
                api_key=ctx.deps.google_api_key,
            )
        )
        audio_bytes = Path(tmp_path).read_bytes()
        caption = text.strip()[:TELEGRAM_CAPTION_MAX]
        await ctx.deps.telegram_client.send_audio(
            ctx.deps.chat_id,
            audio_bytes,
            caption=caption,
        )
    except Exception:
        logger.exception("send_message as_voice failed — falling back to text")
        await _send_text_chunks(ctx, text)
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
