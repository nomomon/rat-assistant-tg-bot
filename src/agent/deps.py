"""Agent dependencies (none required for this agent)."""

from typing import Any

# This agent does not use custom deps; we pass message_history at run time.
# If you add tools that need Redis or user_id, define a dataclass here and use deps_type=...
AgentDeps = dict[str, Any]  # placeholder; agent uses deps_type=None
