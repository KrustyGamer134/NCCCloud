"""
Tests for core.agent_relay.send_command

The relay is a thin adapter: it calls api.agent_ws.send_command_to_agent and
translates HTTPExceptions into plain error dicts so callers can always write an
audit log regardless of outcome.  These tests mock send_command_to_agent
directly and assert on what send_command returns.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_http_exc(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": message, "code": code})


# ---------------------------------------------------------------------------
# Case A — connected agent: command is forwarded, result is returned as-is
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_command_connected_agent_forwards_command():
    expected_result = {"status": "success", "data": {"pid": 1234}}

    with patch(
        "api.agent_ws.send_command_to_agent",
        new_callable=AsyncMock,
        return_value=expected_result,
    ) as mock_send:
        from core.agent_relay import send_command

        result = await send_command(
            agent_id="agent-abc",
            command="start",
            payload={"instance_id": "inst-1"},
        )

    # The command dict forwarded to the underlying function must include the
    # action and the payload fields.
    mock_send.assert_awaited_once()
    call_args = mock_send.call_args
    forwarded_agent_id = call_args.args[0]
    forwarded_dict = call_args.args[1]

    assert forwarded_agent_id == "agent-abc"
    assert forwarded_dict["action"] == "start"
    assert forwarded_dict["instance_id"] == "inst-1"
    assert forwarded_dict["type"] == "command"

    # Result is passed through unchanged.
    assert result == expected_result


# ---------------------------------------------------------------------------
# Case B — offline agent: HTTPException 503 → error dict, no exception raised
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_command_offline_agent_returns_error_dict():
    offline_exc = _make_http_exc(503, "AGENT_OFFLINE", "Agent not connected")

    with patch(
        "api.agent_ws.send_command_to_agent",
        new_callable=AsyncMock,
        side_effect=offline_exc,
    ):
        from core.agent_relay import send_command

        result = await send_command(
            agent_id="agent-offline",
            command="stop",
            payload={"instance_id": "inst-2"},
        )

    assert result["status"] == "error"
    assert result["code"] == "agent_offline"
    assert "not connected" in result["message"].lower()


# ---------------------------------------------------------------------------
# Case C — agent timeout: HTTPException 504 → error dict with agent_timeout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_command_timeout_returns_agent_timeout_error():
    timeout_exc = _make_http_exc(504, "AGENT_TIMEOUT", "Agent command timed out")

    with patch(
        "api.agent_ws.send_command_to_agent",
        new_callable=AsyncMock,
        side_effect=timeout_exc,
    ):
        from core.agent_relay import send_command

        result = await send_command(
            agent_id="agent-slow",
            command="restart",
            payload={"instance_id": "inst-3"},
        )

    assert result["status"] == "error"
    assert result["code"] == "agent_timeout"
    assert "timed out" in result["message"].lower()


# ---------------------------------------------------------------------------
# Case D — unexpected HTTP error: re-raised, not swallowed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_command_unexpected_http_error_is_reraise():
    """A 500 from the underlying layer should propagate, not be silenced."""
    internal_exc = _make_http_exc(500, "INTERNAL_ERROR", "Something broke")

    with patch(
        "api.agent_ws.send_command_to_agent",
        new_callable=AsyncMock,
        side_effect=internal_exc,
    ):
        from core.agent_relay import send_command

        with pytest.raises(HTTPException) as exc_info:
            await send_command(
                agent_id="agent-bad",
                command="start",
                payload={"instance_id": "inst-4"},
            )

    assert exc_info.value.status_code == 500
