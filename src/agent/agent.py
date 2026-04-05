"""Pydantic AI Agent with Gemini and Google Web Search."""

from pathlib import Path

from pydantic_ai import Agent, WebSearchTool
from pydantic_ai.models.google import GoogleModel

from src.agent.deps import AgentDeps
from src.agent.tools import send_message

GEMINI_MODEL = GoogleModel('gemini-3-flash-preview')
PROMPT_PATH = Path(__file__).parent / "prompt.md"
FALLBACK_INSTRUCTIONS = (
    "You are a helpful assistant. Use web search when you need current information. "
    "Be concise and clear in your replies."
)


def _load_instructions() -> str:
    """Load instructions from prompt.md, or use fallback if file is empty or missing."""
    try:
        text = PROMPT_PATH.read_text()
    except OSError:
        return FALLBACK_INSTRUCTIONS
    return text.strip() or FALLBACK_INSTRUCTIONS


def create_agent(
    *,
    model: str = GEMINI_MODEL,
    instructions: str | None = None,
) -> Agent[AgentDeps, str]:
    """Create the Gemini agent with web search and send_message tool."""
    if instructions is None:
        instructions = _load_instructions()
    return Agent(
        model,
        deps_type=AgentDeps,
        builtin_tools=[WebSearchTool()],
        tools=[send_message],
        instructions=instructions,
        retries=1,
    )
