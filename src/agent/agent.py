"""Pydantic AI Agent with Gemini and Google Web Search."""

from pydantic_ai import Agent, WebSearchTool

GEMINI_MODEL = "google-gla:gemini-3-flash"
DEFAULT_INSTRUCTIONS = (
    "You are a helpful assistant. Use web search when you need current information. "
    "Be concise and clear in your replies."
)


def create_agent(
    *,
    model: str = GEMINI_MODEL,
    instructions: str = DEFAULT_INSTRUCTIONS,
) -> Agent[None, str]:
    """Create the Gemini agent with web search capability."""
    return Agent(
        model,
        builtin_tools=[WebSearchTool()],
        instructions=instructions,
        retries=1,
    )
