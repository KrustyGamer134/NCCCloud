from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Agent configuration.  All fields can be set via environment variables or
    a .env file in the working directory.

    Required on first run (before registration):
        CLUSTER_ROOT    - absolute path to the NCC cluster root (e.g. E:/GameServers)

    Required when NCC core is not installed into the environment:
        NCC_REPO_ROOT   - absolute path to the NCC repository root so `core`
                          can be imported without an editable install

    Populated automatically after registration:
        AGENT_ID        - persisted to agent_state.json and re-read on subsequent starts
    """

    model_config = SettingsConfigDict(env_file=".env")

    # Backend endpoints
    backend_ws_url: str = "ws://localhost:8000/agent/ws"
    backend_http_url: str = "http://localhost:8000"

    # Credentials - empty strings on first run; filled after registration
    api_key: str = ""
    agent_id: str = ""

    # Bootstrap key shared with the NCC backend (BOOTSTRAP_API_KEY in backend .env).
    # Required for agent self-registration when agent_state.json does not yet exist.
    bootstrap_api_key: str = ""

    # Tenant this agent belongs to.  Required for bootstrap self-registration
    # (when agent_state.json does not yet exist).  Get this value from the
    # NCC frontend after your first login: Settings -> App -> Tenant ID.
    tenant_id: str = ""

    # Runtime context
    environment: str = "development"

    # Path to the NCC cluster root directory (e.g. E:/GameServers or /srv/gameservers)
    cluster_root: str = ""

    # Optional explicit NCC repo root for importing core when not installed into
    # the current Python environment.
    ncc_repo_root: str = ""

    # Path where agent_id and post-registration api_key are persisted
    agent_state_file: str = "agent_state.json"
