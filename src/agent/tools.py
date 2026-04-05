"""Agent tools — functions the model can call during its turn."""

import logging

from pydantic_ai import RunContext

from src.agent.deps import AgentDeps
from src.researcher.agent import researcher_agent

logger = logging.getLogger(__name__)

TELEGRAM_MAX_LENGTH = 4096


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


async def send_message(ctx: RunContext[AgentDeps], text: str) -> None:
    """Send a reply to the user. Always call this tool to deliver your response.

    Long messages are split automatically at paragraph or line boundaries so
    each chunk stays within Telegram's 4 096-character limit.

    Args:
        text: The full response text to send to the user.
    """
    if not text.strip():
        logger.warning("send_message called with empty text — skipping")
        return

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
