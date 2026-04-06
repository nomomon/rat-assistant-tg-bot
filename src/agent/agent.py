"""Pydantic AI Agent with Gemini — main conversational agent."""

from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModel

from src.agent.deps import AgentDeps
from src.agent.tools import research, send_message
from src.utils import load_prompt

GEMINI_MODEL = GoogleModel('gemini-3.1-pro-preview')
PROMPT_PATH = Path(__file__).parent / "prompt.md"


def create_agent(
    *,
    model: str = GEMINI_MODEL,
    instructions: str | None = None,
) -> Agent[AgentDeps, str]:
    """Create the main conversational agent with send_message and research tools."""
    if instructions is None:
        instructions = load_prompt(PROMPT_PATH)
    return Agent(
        model,
        deps_type=AgentDeps,
        tools=[send_message, research],
        instructions=instructions,
        retries=1,
        output_retries=4,
    )
