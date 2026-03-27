from __future__ import annotations

import os
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ncc_app:changeme@localhost:5432/ncc_test")
os.environ.setdefault("CLERK_JWKS_URL", "https://example.test/.well-known/jwks.json")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("NCC_CORE_PATH", "E:\\NCCCloud")

from api.routes.instances import CreateInstanceBody, create_instance


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_create_instance_provisions_managed_layout_and_allocates_ports():
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    tenant = types.SimpleNamespace(plan="pro")
    plugin_catalog = types.SimpleNamespace(plugin_json={"name": "ark"})

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(tenant),
            _scalar_result(plugin_catalog),
        ]
    )
    db.flush = AsyncMock()
    db.add = MagicMock()

    body = CreateInstanceBody(
        game_system_id="ark",
        display_name="Ark Test",
        agent_id=str(agent_id),
        config_json={"map": "TheIsland_WP"},
    )
    request = types.SimpleNamespace(state=types.SimpleNamespace(user_id="user-1"))

    send_results = [
        {"status": "success", "data": {"action": "created"}},
        {"status": "success", "data": {"game_port": 27015, "rcon_port": 27020}},
        {"status": "success", "data": {"ok": True}},
    ]

    with patch("api.routes.instances.check_instance_limit", new=AsyncMock()), patch(
        "api.routes.instances.is_agent_connected", return_value=True
    ), patch(
        "api.routes.instances.send_command",
        new=AsyncMock(side_effect=send_results),
    ) as mock_send, patch(
        "api.routes.instances.write_audit_log",
        new=AsyncMock(),
    ):
        response = await create_instance(
            body=body,
            request=request,
            tenant_id=str(tenant_id),
            db=db,
        )

    assert response.game_system_id == "ark"
    assert response.config_json["map"] == "TheIsland_WP"
    assert response.config_json["game_port"] == 27015
    assert response.config_json["rcon_port"] == 27020

    commands = [call.kwargs["command"] for call in mock_send.await_args_list]
    assert commands == ["add-instance", "allocate-instance-ports", "configure-instance"]


@pytest.mark.asyncio
async def test_create_instance_uses_display_name_as_ark_map_when_missing():
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    tenant = types.SimpleNamespace(plan="pro")
    plugin_catalog = types.SimpleNamespace(plugin_json={"name": "ark"})

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(tenant),
            _scalar_result(plugin_catalog),
        ]
    )
    db.flush = AsyncMock()
    db.add = MagicMock()

    body = CreateInstanceBody(
        plugin_id="ark_survival_ascended",
        display_name="TheIsland_WP",
        agent_id=str(agent_id),
        config_json={},
    )
    request = types.SimpleNamespace(state=types.SimpleNamespace(user_id="user-1"))

    send_results = [
        {"status": "success", "data": {"action": "created"}},
        {"status": "success", "data": {"game_port": 27015, "rcon_port": 27020}},
        {"status": "success", "data": {"ok": True}},
    ]

    with patch("api.routes.instances.check_instance_limit", new=AsyncMock()), patch(
        "api.routes.instances.is_agent_connected", return_value=True
    ), patch(
        "api.routes.instances.send_command",
        new=AsyncMock(side_effect=send_results),
    ), patch(
        "api.routes.instances.write_audit_log",
        new=AsyncMock(),
    ):
        response = await create_instance(
            body=body,
            request=request,
            tenant_id=str(tenant_id),
            db=db,
        )

    assert response.config_json["map"] == "TheIsland_WP"
    assert response.config_json["game_port"] == 27015
    assert response.config_json["rcon_port"] == 27020
