"""
Tests for CORE-003 v1.2 — status persistence contract.

Coverage:
  1. _handle_status_update writes per-instance status/install_status to DB
  2. _handle_status_update stamps agent_last_seen on ALL agent instances
     (the Phase-1 bulk UPDATE), not just those present in the snapshot
  3. InstanceResponse.from_orm_safe returns the persisted status
     (and agent_online=False) even when the agent has no live connection
  4. agent_last_seen is included in the serialised response
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from api.schemas import InstanceResponse


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

def _make_agent(tenant_id: uuid.UUID | None = None, agent_id: uuid.UUID | None = None):
    """Return a mock Agent ORM object."""
    agent = MagicMock()
    agent.tenant_id = tenant_id or uuid.uuid4()
    agent.agent_id = agent_id or uuid.uuid4()
    return agent


def _make_instance(
    *,
    instance_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    status: str = "stopped",
    install_status: str = "installed",
    agent_last_seen: datetime | None = None,
) -> MagicMock:
    """Return a mock Instance ORM object with realistic fields."""
    inst = MagicMock()
    inst.instance_id = instance_id or uuid.uuid4()
    inst.tenant_id = tenant_id or uuid.uuid4()
    inst.agent_id = agent_id or uuid.uuid4()
    inst.status = status
    inst.install_status = install_status
    inst.agent_last_seen = agent_last_seen
    inst.plugin_id = "ark"
    inst.display_name = "Test Server"
    inst.config_json = {}
    inst.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return inst


def _make_db_session(select_return=None):
    """
    Return a mock AsyncSession wired for use as `async with AsyncSessionLocal() as db`.

    select_return — value that db.execute(...).scalar_one_or_none() will return
                    for the per-instance SELECT calls.
    """
    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)
    # db.add() is synchronous in SQLAlchemy; override so the AsyncMock base
    # class does not produce an "unawaited coroutine" warning.
    mock_db.add = MagicMock()

    # First execute call = Phase-1 bulk UPDATE — result is unused.
    bulk_update_result = MagicMock()

    # Subsequent execute calls = Phase-2 per-instance SELECTs.
    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = select_return

    mock_db.execute.side_effect = [bulk_update_result, select_result]
    return mock_db


# ---------------------------------------------------------------------------
# 1. Per-instance status and install_status are written to the DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_status_update_writes_status_to_db():
    """The status and install_status from the snapshot are persisted on the row."""
    from api.agent_ws import _handle_status_update

    tid = uuid.uuid4()
    aid = uuid.uuid4()
    iid = uuid.uuid4()

    agent = _make_agent(tenant_id=tid, agent_id=aid)
    mock_inst = _make_instance(instance_id=iid, tenant_id=tid, agent_id=aid,
                               status="stopped", install_status="not_installed")
    mock_db = _make_db_session(select_return=mock_inst)

    snapshot = {
        "instances": [
            {
                "instance_id": str(iid),
                "status": "running",
                "install_status": "installed",
            }
        ]
    }

    with patch("api.agent_ws.AsyncSessionLocal", return_value=mock_db), \
         patch("api.websocket.broadcast_to_tenant", new_callable=AsyncMock):
        await _handle_status_update(agent, snapshot)

    # Phase-2 should have mutated the mock instance.
    assert mock_inst.status == "running"
    assert mock_inst.install_status == "installed"
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_status_update_calls_db_add_and_commit():
    """db.add() and db.commit() are both called so the write is not lost."""
    from api.agent_ws import _handle_status_update

    iid = uuid.uuid4()
    agent = _make_agent()
    mock_inst = _make_instance(instance_id=iid)
    mock_db = _make_db_session(select_return=mock_inst)

    with patch("api.agent_ws.AsyncSessionLocal", return_value=mock_db), \
         patch("api.websocket.broadcast_to_tenant", new_callable=AsyncMock):
        await _handle_status_update(
            agent,
            {"instances": [{"instance_id": str(iid), "status": "running"}]},
        )

    mock_db.add.assert_called_once_with(mock_inst)
    mock_db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# 2. Phase-1 bulk UPDATE stamps agent_last_seen on ALL agent instances
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_handle_status_update_issues_bulk_agent_last_seen_update():
    """
    The first DB execute must be a bulk UPDATE (Phase 1) rather than a SELECT.
    We verify this by inspecting the SQLAlchemy statement that was passed to
    execute().
    """
    from api.agent_ws import _handle_status_update
    from sqlalchemy.sql.dml import Update

    tid = uuid.uuid4()
    aid = uuid.uuid4()
    iid = uuid.uuid4()

    agent = _make_agent(tenant_id=tid, agent_id=aid)
    mock_inst = _make_instance(instance_id=iid, tenant_id=tid, agent_id=aid)
    mock_db = _make_db_session(select_return=mock_inst)

    with patch("api.agent_ws.AsyncSessionLocal", return_value=mock_db), \
         patch("api.websocket.broadcast_to_tenant", new_callable=AsyncMock):
        await _handle_status_update(
            agent,
            {"instances": [{"instance_id": str(iid), "status": "running"}]},
        )

    # First call to execute() must be the bulk UPDATE statement.
    first_call_stmt = mock_db.execute.call_args_list[0].args[0]
    assert isinstance(first_call_stmt, Update), (
        "Phase-1 must be a bulk UPDATE statement so ALL agent instances "
        "have their agent_last_seen updated, not just snapshot entries."
    )


@pytest.mark.asyncio
async def test_handle_status_update_bulk_update_targets_correct_agent():
    """The bulk UPDATE is scoped to the correct tenant and agent."""
    from api.agent_ws import _handle_status_update

    tid = uuid.uuid4()
    aid = uuid.uuid4()
    iid = uuid.uuid4()

    agent = _make_agent(tenant_id=tid, agent_id=aid)
    mock_inst = _make_instance(instance_id=iid, tenant_id=tid, agent_id=aid)
    mock_db = _make_db_session(select_return=mock_inst)

    with patch("api.agent_ws.AsyncSessionLocal", return_value=mock_db), \
         patch("api.websocket.broadcast_to_tenant", new_callable=AsyncMock):
        await _handle_status_update(
            agent,
            {"instances": [{"instance_id": str(iid), "status": "running"}]},
        )

    # Compile and inspect the WHERE clause of the bulk UPDATE.
    from sqlalchemy.dialects import postgresql as pg_dialect
    first_stmt = mock_db.execute.call_args_list[0].args[0]
    compiled = str(first_stmt.compile(dialect=pg_dialect.dialect(),
                                      compile_kwargs={"literal_binds": False}))
    # The WHERE clause should reference both tenant_id and agent_id columns.
    assert "tenant_id" in compiled
    assert "agent_id" in compiled


# ---------------------------------------------------------------------------
# 3. InstanceResponse.from_orm_safe returns persisted status when agent offline
# ---------------------------------------------------------------------------

def test_instance_response_returns_persisted_status_when_agent_offline():
    """
    GET /instances/{id} must reflect the DB-persisted status even when the
    assigned agent has no live WebSocket connection.
    """
    tid = uuid.uuid4()
    aid = uuid.uuid4()
    iid = uuid.uuid4()
    last_seen = datetime(2026, 3, 24, 12, 0, 0, tzinfo=timezone.utc)

    mock_inst = _make_instance(
        instance_id=iid,
        tenant_id=tid,
        agent_id=aid,
        status="running",
        install_status="installed",
        agent_last_seen=last_seen,
    )

    # Agent is NOT in the live connections dict.
    with patch("api.routes.agents.is_agent_connected", return_value=False):
        response = InstanceResponse.from_orm_safe(mock_inst)

    assert response.status == "running"
    assert response.install_status == "installed"
    assert response.agent_online is False


def test_instance_response_agent_online_true_when_connected():
    """agent_online is True when is_agent_connected returns True."""
    mock_inst = _make_instance()

    with patch("api.routes.agents.is_agent_connected", return_value=True):
        response = InstanceResponse.from_orm_safe(mock_inst)

    assert response.agent_online is True


# ---------------------------------------------------------------------------
# 4. agent_last_seen is present and correctly formatted in the response
# ---------------------------------------------------------------------------

def test_instance_response_includes_agent_last_seen():
    """agent_last_seen is serialised as an ISO-8601 string in the response."""
    last_seen = datetime(2026, 3, 24, 15, 30, 0, tzinfo=timezone.utc)
    mock_inst = _make_instance(agent_last_seen=last_seen)

    with patch("api.routes.agents.is_agent_connected", return_value=False):
        response = InstanceResponse.from_orm_safe(mock_inst)

    assert response.agent_last_seen == last_seen.isoformat()


def test_instance_response_agent_last_seen_none_when_never_seen():
    """agent_last_seen is None when the agent has never sent a status update."""
    mock_inst = _make_instance(agent_last_seen=None)

    with patch("api.routes.agents.is_agent_connected", return_value=False):
        response = InstanceResponse.from_orm_safe(mock_inst)

    assert response.agent_last_seen is None


def test_instance_response_agent_online_false_when_no_agent_assigned():
    """agent_online is False when no agent is assigned to the instance."""
    mock_inst = _make_instance()
    mock_inst.agent_id = None  # no agent assigned

    with patch("api.routes.agents.is_agent_connected", return_value=True):
        response = InstanceResponse.from_orm_safe(mock_inst)

    assert response.agent_online is False
    assert response.agent_id is None
