"""Pydantic AI Agent with Gemini — main conversational agent."""

from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel

from src.agent.deps import AgentDeps
from src.agent.tools import research, send_message

GEMINI_MODEL = GoogleModel('gemini-3.1-pro-preview')
PROMPT_PATH = Path(__file__).parent / "prompt.md"
FALLBACK_INSTRUCTIONS = (
    "You are a helpful assistant. Use the research tool when you need current information "
    "from the web. Be concise and clear in your replies. Always call send_message to reply."
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
    """Create the main conversational agent with send_message and research tools."""
    if instructions is None:
        instructions = _load_instructions()
    return Agent(
        model,
        deps_type=AgentDeps,
        tools=[send_message, research],
        instructions=instructions,
        retries=1,
    )
