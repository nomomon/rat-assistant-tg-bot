"""Researcher sub-agent: web search only, returns a report string."""

from pathlib import Path

from pydantic_ai import Agent, WebSearchTool
from pydantic_ai.models.google import GoogleModel

GEMINI_MODEL = GoogleModel('gemini-2.5-pro-preview-03-25')
PROMPT_PATH = Path(__file__).parent / "prompt.md"
FALLBACK_INSTRUCTIONS = (
    "You are a research assistant. Search the web to answer the query thoroughly. "
    "Return a structured report with sources."
)


def _load_instructions() -> str:
    try:
        text = PROMPT_PATH.read_text()
    except OSError:
        return FALLBACK_INSTRUCTIONS
    return text.strip() or FALLBACK_INSTRUCTIONS


def create_researcher_agent() -> Agent[None, str]:
    """Create the researcher agent with web search only (no function tools)."""
    return Agent(
        GEMINI_MODEL,
        deps_type=None,
        builtin_tools=[WebSearchTool()],
        instructions=_load_instructions(),
        retries=1,
    )


researcher_agent = create_researcher_agent()
