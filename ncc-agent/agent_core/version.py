"""Single source of truth for agent version constants."""

# Reported to the backend in every hello message.
AGENT_VERSION: str = "0.1.0"

# Minimum backend version this agent is compatible with.
# Reserved for future use — the agent does not currently validate backend version.
MIN_BACKEND_VERSION: str = "0.1.0"
