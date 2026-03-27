"""
Tests for CORE-002 — agent version compatibility handshake.

Coverage
--------
Unit tests (pure function, no I/O):
  1. _check_agent_version returns "rejected" for versions below MIN
  2. _check_agent_version returns "ok" for versions at or above MIN
  3. _check_agent_version returns "warn" when no version is reported
  4. _check_agent_version returns "rejected" for invalid version strings

Integration tests (mock WebSocket + mock DB):
  5. version_rejected  — agent sends "0.0.1" (below MIN "0.1.0")
       → hello_ack {"type":"hello_ack","status":"rejected"} sent before close
       → WebSocket closed with code 4003
       → agent is NOT added to _agent_connections
  6. version_accepted  — agent sends "0.1.0" (== MIN)
       → hello_ack {"type":"hello_ack","status":"ok"} sent
       → WebSocket NOT closed with 4003
  7. db_updated        — after an accepted hello the agent DB row is updated:
       agent_version, last_seen, and public_ip are all written before hello_ack
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_agent(
    *,
    agent_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    agent_version: str | None = None,
    public_ip: str | None = None,
    last_seen: datetime | None = None,
) -> MagicMock:
    agent = MagicMock()
    agent.agent_id = agent_id or uuid.uuid4()
    agent.tenant_id = tenant_id or uuid.uuid4()
    agent.agent_version = agent_version
    agent.public_ip = public_ip
    agent.last_seen = last_seen
    agent.is_revoked = False
    return agent


def _make_websocket(hello_payload: dict, *, disconnect_after_hello: bool = True):
    """
    Return a mock FastAPI WebSocket.

    receive_json() returns hello_payload on the first call; if
    disconnect_after_hello is True the second call raises WebSocketDisconnect
    so the message loop exits cleanly.
    """
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()

    if disconnect_after_hello:
        ws.receive_json = AsyncMock(
            side_effect=[hello_payload, WebSocketDisconnect()]
        )
    else:
        ws.receive_json = AsyncMock(return_value=hello_payload)

    return ws


def _make_db_session(db_agent: MagicMock | None = None) -> AsyncMock:
    """
    Return a mock AsyncSession for use as ``async with AsyncSessionLocal() as db``.

    execute() returns a result whose scalar_one_or_none() yields *db_agent*.
    db.add() and db.commit() are tracked for assertions.
    """
    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)
    mock_db.add = MagicMock()

    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = db_agent
    mock_db.execute = AsyncMock(return_value=select_result)
    return mock_db


# ---------------------------------------------------------------------------
# 1-4: Unit tests for _check_agent_version (pure function)
# ---------------------------------------------------------------------------

def test_check_version_rejected_below_min():
    """`0.0.1` is below the minimum `0.1.0` → rejected."""
    from api.agent_ws import _check_agent_version

    status, msg = _check_agent_version("0.0.1")

    assert status == "rejected"
    assert "0.0.1" in msg
    assert "0.1.0" in msg


def test_check_version_ok_at_min():
    """`0.1.0` exactly matches MIN → ok."""
    from api.agent_ws import _check_agent_version

    status, msg = _check_agent_version("0.1.0")

    assert status == "ok"
    assert msg == ""


def test_check_version_ok_above_min():
    """`1.0.0` is above MIN `0.1.0` → ok."""
    from api.agent_ws import _check_agent_version

    status, msg = _check_agent_version("1.0.0")

    assert status == "ok"
    assert msg == ""


def test_check_version_warn_when_none():
    """Missing version string → warn (not rejected)."""
    from api.agent_ws import _check_agent_version

    status, msg = _check_agent_version(None)

    assert status == "warn"
    assert msg  # non-empty message


def test_check_version_rejected_invalid_string():
    """A non-PEP-440 version string → rejected."""
    from api.agent_ws import _check_agent_version

    status, msg = _check_agent_version("not-a-version")

    assert status == "rejected"


# ---------------------------------------------------------------------------
# 5: version_rejected — below-minimum agent is bounced before entering loop
# ---------------------------------------------------------------------------

async def test_version_rejected_sends_ack_and_closes():
    """
    An agent reporting version "0.0.1" (below MIN_SUPPORTED_AGENT "0.1.0")
    must receive a rejected hello_ack and have its connection closed.
    """
    from api.agent_ws import agent_ws_endpoint

    agent = _make_agent()
    ws = _make_websocket(
        {
            "type": "hello",
            "agent_id": str(agent.agent_id),
            "api_key": "test-key",
            "agent_version": "0.0.1",
            "public_ip": None,
        },
        disconnect_after_hello=False,  # loop never reached for rejected agents
    )
    mock_db = _make_db_session(agent)

    with patch("api.agent_ws._authenticate_agent", new_callable=AsyncMock, return_value=agent), \
         patch("api.agent_ws.AsyncSessionLocal", return_value=mock_db):
        await agent_ws_endpoint(ws)

    # A hello_ack with status="rejected" must have been sent.
    sent = [call.args[0] for call in ws.send_json.call_args_list]
    rejected_acks = [
        m for m in sent
        if m.get("type") == "hello_ack" and m.get("status") == "rejected"
    ]
    assert rejected_acks, (
        f"Expected a rejected hello_ack but send_json was called with: {sent}"
    )

    # The connection must have been closed with code 4003.
    ws.close.assert_awaited_once()
    close_kwargs = ws.close.call_args.kwargs
    assert close_kwargs.get("code") == 4003, (
        f"Expected close(code=4003) but got: {ws.close.call_args}"
    )


async def test_version_rejected_not_added_to_connections():
    """A rejected agent must not appear in the live _agent_connections dict."""
    from api.agent_ws import _agent_connections, agent_ws_endpoint

    agent = _make_agent()
    agent_id_str = str(agent.agent_id)
    ws = _make_websocket(
        {
            "type": "hello",
            "agent_id": agent_id_str,
            "api_key": "test-key",
            "agent_version": "0.0.1",
            "public_ip": None,
        },
        disconnect_after_hello=False,
    )
    mock_db = _make_db_session(agent)

    with patch("api.agent_ws._authenticate_agent", new_callable=AsyncMock, return_value=agent), \
         patch("api.agent_ws.AsyncSessionLocal", return_value=mock_db):
        await agent_ws_endpoint(ws)

    assert agent_id_str not in _agent_connections, (
        "Rejected agent must not be registered in live connections"
    )


# ---------------------------------------------------------------------------
# 6: version_accepted — at-minimum agent gets ok ack and enters message loop
# ---------------------------------------------------------------------------

async def test_version_accepted_sends_ok_ack():
    """
    An agent reporting version "0.1.0" (== MIN_SUPPORTED_AGENT) must receive
    a hello_ack with status "ok" and must NOT be closed with 4003.
    """
    from api.agent_ws import agent_ws_endpoint

    agent = _make_agent()
    ws = _make_websocket(
        {
            "type": "hello",
            "agent_id": str(agent.agent_id),
            "api_key": "test-key",
            "agent_version": "0.1.0",
            "public_ip": "203.0.113.1",
        }
    )
    mock_db = _make_db_session(agent)

    with patch("api.agent_ws._authenticate_agent", new_callable=AsyncMock, return_value=agent), \
         patch("api.agent_ws.AsyncSessionLocal", return_value=mock_db):
        await agent_ws_endpoint(ws)

    # hello_ack with status="ok" must have been sent.
    sent = [call.args[0] for call in ws.send_json.call_args_list]
    ok_acks = [m for m in sent if m.get("type") == "hello_ack" and m.get("status") == "ok"]
    assert ok_acks, f"Expected hello_ack status='ok' but got: {sent}"

    # Connection must NOT have been closed with 4003.
    for call in ws.close.call_args_list:
        assert call.kwargs.get("code") != 4003, (
            "Accepted agent must not be closed with code 4003"
        )


# ---------------------------------------------------------------------------
# 7: db_updated — accepted hello writes agent_version, last_seen, public_ip
# ---------------------------------------------------------------------------

async def test_db_updated_after_accepted_hello():
    """
    After a successful hello the agent DB row must be updated in a single
    commit with:
      - agent_version set to the value from the hello message
      - last_seen set to a recent UTC timestamp
      - public_ip set to the IP from the hello message
    """
    from api.agent_ws import agent_ws_endpoint

    agent = _make_agent(agent_version=None, public_ip=None, last_seen=None)
    ws = _make_websocket(
        {
            "type": "hello",
            "agent_id": str(agent.agent_id),
            "api_key": "test-key",
            "agent_version": "0.1.0",
            "public_ip": "203.0.113.42",
        }
    )
    mock_db = _make_db_session(agent)

    before = datetime.now(tz=timezone.utc)

    with patch("api.agent_ws._authenticate_agent", new_callable=AsyncMock, return_value=agent), \
         patch("api.agent_ws.AsyncSessionLocal", return_value=mock_db):
        await agent_ws_endpoint(ws)

    after = datetime.now(tz=timezone.utc)

    # agent_version must be written.
    assert agent.agent_version == "0.1.0", (
        f"Expected agent_version='0.1.0', got {agent.agent_version!r}"
    )

    # public_ip must be written.
    assert agent.public_ip == "203.0.113.42", (
        f"Expected public_ip='203.0.113.42', got {agent.public_ip!r}"
    )

    # last_seen must be a recent UTC datetime.
    assert agent.last_seen is not None, "last_seen must not be None after hello"
    assert before <= agent.last_seen <= after, (
        f"last_seen {agent.last_seen} is outside the expected window "
        f"[{before}, {after}]"
    )

    # All three writes must go out in a single commit.
    mock_db.commit.assert_awaited_once()


async def test_db_public_ip_not_overwritten_when_unchanged():
    """
    If the agent sends the same public_ip that is already stored, the field
    must still be set (idempotent) and no errors raised.
    """
    from api.agent_ws import agent_ws_endpoint

    existing_ip = "203.0.113.99"
    agent = _make_agent(public_ip=existing_ip)
    ws = _make_websocket(
        {
            "type": "hello",
            "agent_id": str(agent.agent_id),
            "api_key": "test-key",
            "agent_version": "0.1.0",
            "public_ip": existing_ip,
        }
    )
    mock_db = _make_db_session(agent)

    with patch("api.agent_ws._authenticate_agent", new_callable=AsyncMock, return_value=agent), \
         patch("api.agent_ws.AsyncSessionLocal", return_value=mock_db):
        await agent_ws_endpoint(ws)

    # The IP must remain the same and the commit must still happen.
    assert agent.public_ip == existing_ip
    mock_db.commit.assert_awaited_once()


async def test_db_public_ip_skipped_when_none():
    """
    If the agent sends public_ip=None the field must not overwrite an existing
    stored IP (agent.public_ip stays at whatever it was before).
    """
    from api.agent_ws import agent_ws_endpoint

    existing_ip = "203.0.113.55"
    agent = _make_agent(public_ip=existing_ip)
    ws = _make_websocket(
        {
            "type": "hello",
            "agent_id": str(agent.agent_id),
            "api_key": "test-key",
            "agent_version": "0.1.0",
            "public_ip": None,
        }
    )
    mock_db = _make_db_session(agent)

    with patch("api.agent_ws._authenticate_agent", new_callable=AsyncMock, return_value=agent), \
         patch("api.agent_ws.AsyncSessionLocal", return_value=mock_db):
        await agent_ws_endpoint(ws)

    # public_ip must not have been clobbered with None.
    assert agent.public_ip == existing_ip, (
        f"public_ip must not be overwritten by None, but got {agent.public_ip!r}"
    )
