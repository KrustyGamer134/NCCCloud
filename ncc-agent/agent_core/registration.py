"""
Agent registration.

On first run the agent POSTs to /agents/register with a bootstrap API key to
obtain a permanent agent_id and api_key.  Those credentials are written to
agent_state.json so subsequent runs skip registration entirely.
"""

import json
import logging
import socket
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


def load_agent_state(settings) -> dict | None:
    """
    Read agent_state.json from the path configured in settings.
    Returns the parsed dict, or None if the file does not exist or cannot be read.
    """
    path = Path(settings.agent_state_file)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.warning("Failed to read agent state file %s: %s", path, exc)
        return None


def _save_agent_state(settings, agent_id: str, api_key: str) -> None:
    path = Path(settings.agent_state_file)
    try:
        with path.open("w", encoding="utf-8") as fh:
            json.dump({"agent_id": agent_id, "api_key": api_key}, fh, indent=2)
        logger.info("Agent state saved to %s", path)
    except Exception as exc:
        logger.error("Failed to save agent state to %s: %s", path, exc)


async def ensure_registered(settings) -> tuple[str, str]:
    """
    Return (agent_id, api_key).

    If agent_state.json already contains an agent_id the agent is considered
    registered and the stored credentials are returned immediately.  Otherwise,
    the agent registers with the NCC backend using the bootstrap api_key from
    .env and persists the result.
    """
    state = load_agent_state(settings)
    if state and state.get("agent_id"):
        agent_id = state["agent_id"]
        # Prefer the api_key stored in state; fall back to the .env value so
        # the agent can still boot if the state file predates api_key storage.
        api_key = state.get("api_key") or settings.api_key
        logger.info("Agent already registered: agent_id=%s", agent_id)
        return agent_id, api_key

    logger.info("No registration found — registering with backend at %s", settings.backend_http_url)

    if not settings.tenant_id:
        logger.error(
            "TENANT_ID is not set. Cannot self-register. "
            "Set TENANT_ID in the agent .env (find your tenant ID in the NCC frontend Settings page)."
        )
        raise ValueError("TENANT_ID must be set for agent self-registration")

    url = f"{settings.backend_http_url}/agents/register"
    bootstrap_key = settings.bootstrap_api_key or settings.api_key
    if not bootstrap_key:
        raise ValueError("BOOTSTRAP_API_KEY must be set for agent self-registration")
    headers = {"Authorization": f"Bearer {bootstrap_key}"}
    body = {"machine_name": socket.gethostname(), "tenant_id": settings.tenant_id}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=body, headers=headers)
    except httpx.ConnectError as exc:
        logger.error("Cannot reach backend at %s: %s", url, exc)
        raise
    except httpx.TimeoutException as exc:
        logger.error("Timed out connecting to backend at %s: %s", url, exc)
        raise

    if response.status_code not in (200, 201):
        logger.error(
            "Registration failed: HTTP %s — %s",
            response.status_code,
            response.text[:500],
        )
        response.raise_for_status()

    try:
        data = response.json()
    except Exception as exc:
        logger.error("Registration response is not valid JSON: %s", exc)
        raise

    agent_id = data.get("agent_id") or data.get("id")
    api_key = data.get("api_key") or data.get("key")

    if not agent_id or not api_key:
        raise ValueError(
            f"Registration response missing agent_id or api_key. Got: {data}"
        )

    _save_agent_state(settings, agent_id, api_key)
    logger.info("Registration successful: agent_id=%s", agent_id)
    return agent_id, api_key
