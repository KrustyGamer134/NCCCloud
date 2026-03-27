from __future__ import annotations

import logging

from fastapi import HTTPException

logger = logging.getLogger(__name__)


async def send_command(agent_id: str, command: str, payload: dict) -> dict:
    """
    Forward a command to the named agent via the live WebSocket connection.

    Always returns a dict - never raises - so callers can unconditionally
    write an audit log regardless of outcome.

    Return shapes:
      success  -> whatever send_command_to_agent returns (status/data from agent)
      offline  -> {"status": "error", "code": "agent_offline",  "message": "..."}
      timeout  -> {"status": "error", "code": "agent_timeout",  "message": "..."}
    """
    from api.agent_ws import send_command_to_agent

    command_dict = {"type": "command", "action": command.replace("-", "_"), **payload}

    try:
        return await send_command_to_agent(agent_id, command_dict)
    except HTTPException as exc:
        if exc.status_code == 503:
            return {
                "status": "error",
                "code": "agent_offline",
                "message": "Agent is not connected",
            }
        if exc.status_code == 504:
            return {
                "status": "error",
                "code": "agent_timeout",
                "message": "Agent command timed out",
            }
        raise
