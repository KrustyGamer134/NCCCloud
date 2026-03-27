"""
Tests for core.plan_limits — BILL-001.

Two layers:

Unit tests (mock DB, no PostgreSQL required)
--------------------------------------------
Exercise check_instance_limit / check_agent_limit by injecting a mock
AsyncSession whose execute() returns a controllable scalar count.  Fast and
always runnable.

Integration tests (real DB, require PostgreSQL)
------------------------------------------------
Use the ``db_session`` fixture from conftest.py to INSERT real rows and
call the check functions against actual DB queries.  These tests are skipped
automatically when DATABASE_URL_TEST is not reachable (see conftest.py).

They also call ``list_plugins`` directly (bypassing FastAPI DI) to verify
the pro/free filter logic end-to-end with real plugin_catalog rows.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from core.plan_limits import (
    PLAN_LIMITS,
    check_agent_limit,
    check_instance_limit,
    get_limits,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(count: int) -> AsyncMock:
    """Return a mock AsyncSession whose execute() yields scalar_one() == count."""
    mock_result = MagicMock()
    mock_result.scalar_one.return_value = count
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result
    return mock_db


def _tenant_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Unit tests: get_limits / PLAN_LIMITS sanity
# ---------------------------------------------------------------------------

def test_plan_limits_keys_present():
    for plan in ("free", "basic", "pro"):
        limits = get_limits(plan)
        assert "max_instances" in limits
        assert "max_agents" in limits
        assert "plugins" in limits


def test_unknown_plan_falls_back_to_free():
    limits = get_limits("enterprise_plus_ultra")
    free_limits = get_limits("free")
    assert limits == free_limits


@pytest.mark.asyncio
async def test_list_plugins_exposes_map_provisioning_metadata():
    from api.routes.plugins import list_plugins

    tenant_id = _tenant_id()
    tenant = MagicMock()
    tenant.plan = "pro"
    plugin = MagicMock()
    plugin.plugin_id = "ark"
    plugin.display_name = "ARK: Survival Ascended"
    plugin.description = "ARK"
    plugin.available_in_plans = ["free", "pro"]
    plugin.plugin_json = {
        "maps": {
            "TheIsland_WP": {"display_name": "The Island"},
            "ScorchedEarth_WP": {"display_name": "Scorched Earth"},
        },
        "server_settings": {
            "map": {"value": "TheIsland_WP"},
        },
    }

    tenant_result = MagicMock()
    tenant_result.scalar_one_or_none.return_value = tenant
    plugins_result = MagicMock()
    plugins_result.scalars.return_value.all.return_value = [plugin]
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[tenant_result, plugins_result])

    result = await list_plugins(tenant_id=tenant_id, db=db)

    assert len(result) == 1
    assert result[0].provisioning == {
        "default_map": "TheIsland_WP",
        "maps": [
            {"id": "TheIsland_WP", "display_name": "The Island"},
            {"id": "ScorchedEarth_WP", "display_name": "Scorched Earth"},
        ],
    }


def test_pro_has_no_hard_limits():
    limits = get_limits("pro")
    assert limits["max_instances"] is None
    assert limits["max_agents"] is None


def test_free_limits_are_correct():
    limits = get_limits("free")
    assert limits["max_instances"] == 1
    assert limits["max_agents"] == 1


def test_basic_limits_are_correct():
    limits = get_limits("basic")
    assert limits["max_instances"] == 3
    assert limits["max_agents"] == 2


# ---------------------------------------------------------------------------
# Instance limit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_free_at_instance_limit_raises_402():
    """Free tenant with 1 existing instance cannot create a second."""
    db = _make_db(count=1)

    with pytest.raises(HTTPException) as exc_info:
        await check_instance_limit(db, _tenant_id(), "free")

    exc = exc_info.value
    assert exc.status_code == 402
    detail = exc.detail
    assert detail["code"] == "plan_limit_reached"
    assert detail["limit_type"] == "instances"
    assert detail["current"] == 1
    assert detail["max"] == 1


@pytest.mark.asyncio
async def test_free_under_instance_limit_passes():
    """Free tenant with 0 instances can create one."""
    db = _make_db(count=0)
    # Must not raise
    await check_instance_limit(db, _tenant_id(), "free")


@pytest.mark.asyncio
async def test_basic_at_instance_limit_raises_402():
    """Basic tenant with 3 instances cannot create a fourth."""
    db = _make_db(count=3)

    with pytest.raises(HTTPException) as exc_info:
        await check_instance_limit(db, _tenant_id(), "basic")

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["max"] == 3


@pytest.mark.asyncio
async def test_basic_under_instance_limit_passes():
    db = _make_db(count=2)
    await check_instance_limit(db, _tenant_id(), "basic")


@pytest.mark.asyncio
async def test_pro_never_blocked_on_instances():
    """Pro tenant with any number of instances is never blocked."""
    db = _make_db(count=9_999)
    # Must not raise and must not even query the DB.
    await check_instance_limit(db, _tenant_id(), "pro")
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_instance_limit_error_shape():
    """Verify the full error body shape for instance limits."""
    db = _make_db(count=1)

    with pytest.raises(HTTPException) as exc_info:
        await check_instance_limit(db, _tenant_id(), "free")

    detail = exc_info.value.detail
    assert detail["error"] == "plan_limit_reached"
    assert detail["code"] == "plan_limit_reached"
    assert detail["limit_type"] == "instances"
    assert isinstance(detail["current"], int)
    assert isinstance(detail["max"], int)


# ---------------------------------------------------------------------------
# Agent limit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_free_at_agent_limit_raises_402():
    """Free tenant with 1 active agent cannot register a second."""
    db = _make_db(count=1)

    with pytest.raises(HTTPException) as exc_info:
        await check_agent_limit(db, _tenant_id(), "free")

    exc = exc_info.value
    assert exc.status_code == 402
    detail = exc.detail
    assert detail["code"] == "plan_limit_reached"
    assert detail["limit_type"] == "agents"
    assert detail["current"] == 1
    assert detail["max"] == 1


@pytest.mark.asyncio
async def test_free_under_agent_limit_passes():
    """Free tenant with 0 active agents can register one."""
    db = _make_db(count=0)
    await check_agent_limit(db, _tenant_id(), "free")


@pytest.mark.asyncio
async def test_basic_at_agent_limit_raises_402():
    """Basic tenant with 2 agents cannot register a third."""
    db = _make_db(count=2)

    with pytest.raises(HTTPException) as exc_info:
        await check_agent_limit(db, _tenant_id(), "basic")

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail["max"] == 2


@pytest.mark.asyncio
async def test_basic_under_agent_limit_passes():
    db = _make_db(count=1)
    await check_agent_limit(db, _tenant_id(), "basic")


@pytest.mark.asyncio
async def test_pro_never_blocked_on_agents():
    """Pro tenant with any number of agents is never blocked."""
    db = _make_db(count=9_999)
    await check_agent_limit(db, _tenant_id(), "pro")
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_limit_error_shape():
    """Verify the full error body shape for agent limits."""
    db = _make_db(count=1)

    with pytest.raises(HTTPException) as exc_info:
        await check_agent_limit(db, _tenant_id(), "free")

    detail = exc_info.value.detail
    assert detail["error"] == "plan_limit_reached"
    assert detail["code"] == "plan_limit_reached"
    assert detail["limit_type"] == "agents"
    assert isinstance(detail["current"], int)
    assert isinstance(detail["max"], int)


# ===========================================================================
# Integration tests — real PostgreSQL, real rows, real SQL queries
# ===========================================================================
# These tests use the ``db_session`` fixture from tests/conftest.py.
# They are skipped automatically when DATABASE_URL_TEST is unreachable.
#
# Each test inserts its own Tenant + resource rows, calls the check function
# (or the route handler directly), and asserts the result.  The db_session
# fixture rolls back after every test, so rows never bleed across tests.
# ===========================================================================

import uuid as _uuid  # shadow-free alias for use inside helpers

from db.models import Agent as _Agent
from db.models import Instance as _Instance
from db.models import PluginCatalog as _PluginCatalog
from db.models import Tenant as _Tenant


# ---------------------------------------------------------------------------
# DB row helpers
# ---------------------------------------------------------------------------

async def _make_tenant(db, plan: str) -> _Tenant:
    t = _Tenant(tenant_id=_uuid.uuid4(), name="test-tenant", plan=plan)
    db.add(t)
    await db.flush()
    return t


async def _make_instances(db, tenant_id: _uuid.UUID, count: int) -> None:
    for _ in range(count):
        db.add(
            _Instance(
                instance_id=_uuid.uuid4(),
                tenant_id=tenant_id,
                plugin_id="ark_survival_ascended",
                display_name="test",
                config_json={},
                status="unknown",
                install_status="not_installed",
            )
        )
    await db.flush()


async def _make_agents(
    db, tenant_id: _uuid.UUID, count: int, *, revoked: bool = False
) -> None:
    for _ in range(count):
        db.add(
            _Agent(
                agent_id=_uuid.uuid4(),
                tenant_id=tenant_id,
                machine_name="test-machine",
                api_key_hash="placeholder",
                is_revoked=revoked,
            )
        )
    await db.flush()


async def _make_plugin(
    db, plugin_id: str, available_in_plans: list[str]
) -> _PluginCatalog:
    p = _PluginCatalog(
        plugin_id=plugin_id,
        display_name=plugin_id,
        plugin_json={},
        available_in_plans=available_in_plans,
    )
    db.add(p)
    await db.flush()
    return p


# ---------------------------------------------------------------------------
# Instance limit — integration
# ---------------------------------------------------------------------------

async def test_integ_free_at_instance_limit_raises_402(db_session):
    """free tenant with 1 instance (at limit) → 402."""
    t = await _make_tenant(db_session, "free")
    await _make_instances(db_session, t.tenant_id, count=1)

    with pytest.raises(HTTPException) as exc_info:
        await check_instance_limit(db_session, str(t.tenant_id), "free")

    exc = exc_info.value
    assert exc.status_code == 402
    assert exc.detail["limit_type"] == "instances"
    assert exc.detail["current"] == 1
    assert exc.detail["max"] == 1


async def test_integ_free_under_instance_limit_passes(db_session):
    """free tenant with 0 instances (under limit) → passes."""
    t = await _make_tenant(db_session, "free")
    # No instances inserted — count is 0, limit is 1.
    await check_instance_limit(db_session, str(t.tenant_id), "free")


async def test_integ_basic_at_instance_limit_raises_402(db_session):
    """basic tenant with 3 instances (at limit) → 402."""
    t = await _make_tenant(db_session, "basic")
    await _make_instances(db_session, t.tenant_id, count=3)

    with pytest.raises(HTTPException) as exc_info:
        await check_instance_limit(db_session, str(t.tenant_id), "basic")

    exc = exc_info.value
    assert exc.status_code == 402
    assert exc.detail["current"] == 3
    assert exc.detail["max"] == 3


async def test_integ_basic_under_instance_limit_passes(db_session):
    """basic tenant with 2 instances (under limit of 3) → passes."""
    t = await _make_tenant(db_session, "basic")
    await _make_instances(db_session, t.tenant_id, count=2)
    await check_instance_limit(db_session, str(t.tenant_id), "basic")


async def test_integ_pro_never_blocked_on_instances(db_session):
    """pro tenant with many instances is never blocked."""
    t = await _make_tenant(db_session, "pro")
    await _make_instances(db_session, t.tenant_id, count=50)
    # Must not raise, and must not issue a COUNT query at all.
    await check_instance_limit(db_session, str(t.tenant_id), "pro")


# ---------------------------------------------------------------------------
# Agent limit — integration
# ---------------------------------------------------------------------------

async def test_integ_free_at_agent_limit_raises_402(db_session):
    """free tenant with 1 active agent (at limit) → 402."""
    t = await _make_tenant(db_session, "free")
    await _make_agents(db_session, t.tenant_id, count=1)

    with pytest.raises(HTTPException) as exc_info:
        await check_agent_limit(db_session, str(t.tenant_id), "free")

    exc = exc_info.value
    assert exc.status_code == 402
    assert exc.detail["limit_type"] == "agents"
    assert exc.detail["current"] == 1
    assert exc.detail["max"] == 1


async def test_integ_free_revoked_agent_not_counted(db_session):
    """A revoked agent does not consume a slot — free tenant can still register."""
    t = await _make_tenant(db_session, "free")
    # One revoked agent: should not count toward the limit.
    await _make_agents(db_session, t.tenant_id, count=1, revoked=True)
    # Must not raise (current non-revoked count is 0, limit is 1).
    await check_agent_limit(db_session, str(t.tenant_id), "free")


async def test_integ_pro_never_blocked_on_agents(db_session):
    """pro tenant with many agents is never blocked."""
    t = await _make_tenant(db_session, "pro")
    await _make_agents(db_session, t.tenant_id, count=20)
    await check_agent_limit(db_session, str(t.tenant_id), "pro")


# ---------------------------------------------------------------------------
# Plugin filter — integration
# ---------------------------------------------------------------------------

async def test_integ_plugins_free_gets_subset_pro_gets_all(db_session):
    """
    Plugin filter: free tenant sees only plugins that list "free" in
    available_in_plans; pro tenant sees all catalog plugins unconditionally.

    We call list_plugins() directly (bypassing FastAPI DI) with the same
    db_session and an explicit tenant_id so the test does not need an HTTP
    client or JWT middleware.
    """
    from api.routes.plugins import list_plugins

    # Set up two tenants.
    free_tenant = await _make_tenant(db_session, "free")
    pro_tenant = await _make_tenant(db_session, "pro")

    # Insert two catalog plugins with different plan coverage.
    # Use unique IDs so this test is isolated from other plugin rows.
    uid = str(_uuid.uuid4())[:8]
    await _make_plugin(
        db_session,
        plugin_id=f"ark_test_{uid}",
        available_in_plans=["free", "basic", "pro"],
    )
    await _make_plugin(
        db_session,
        plugin_id=f"premium_test_{uid}",
        available_in_plans=["basic", "pro"],  # NOT available to free
    )

    # ── Free tenant: should only see the first plugin ───────────────────
    free_result = await list_plugins(
        tenant_id=str(free_tenant.tenant_id), db=db_session
    )
    free_ids = {p.plugin_id for p in free_result}

    assert f"ark_test_{uid}" in free_ids, "free tenant must see the free plugin"
    assert f"premium_test_{uid}" not in free_ids, (
        "free tenant must NOT see the premium-only plugin"
    )

    # ── Pro tenant: must see both plugins ────────────────────────────────
    pro_result = await list_plugins(
        tenant_id=str(pro_tenant.tenant_id), db=db_session
    )
    pro_ids = {p.plugin_id for p in pro_result}

    assert f"ark_test_{uid}" in pro_ids, "pro tenant must see all plugins"
    assert f"premium_test_{uid}" in pro_ids, "pro tenant must see the premium plugin"


async def test_integ_pro_sees_plugin_not_in_any_plan_list(db_session):
    """
    Pro tenants bypass available_in_plans entirely.
    A plugin with available_in_plans=[] (empty) is still visible to pro.
    """
    from api.routes.plugins import list_plugins

    pro_tenant = await _make_tenant(db_session, "pro")
    uid = str(_uuid.uuid4())[:8]

    await _make_plugin(
        db_session,
        plugin_id=f"unlisted_test_{uid}",
        available_in_plans=[],  # not listed for any plan
    )

    pro_result = await list_plugins(
        tenant_id=str(pro_tenant.tenant_id), db=db_session
    )
    pro_ids = {p.plugin_id for p in pro_result}

    assert f"unlisted_test_{uid}" in pro_ids, (
        "pro tenant must see plugins even when available_in_plans is empty"
    )
