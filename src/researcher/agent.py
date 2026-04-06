"""Researcher sub-agent: web search only, returns a report string."""

from pathlib import Path

from pydantic_ai import Agent, WebSearchTool
from pydantic_ai.models.google import GoogleModel

from src.utils import load_prompt

GEMINI_MODEL = GoogleModel('gemini-3-flash-preview')
PROMPT_PATH = Path(__file__).parent / "prompt.md"


def create_researcher_agent() -> Agent[None, str]:
    """Create the researcher agent with web search only (no function tools)."""
    return Agent(
        GEMINI_MODEL,
        deps_type=None,
        builtin_tools=[WebSearchTool()],
        instructions=load_prompt(PROMPT_PATH),
        retries=1,
        output_retries=4,
    )


researcher_agent = create_researcher_agent()
