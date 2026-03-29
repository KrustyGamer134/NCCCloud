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

from fastapi import HTTPException

from api.routes.settings import (
    InstanceConfigBody,
    PluginSettingsBody,
    get_instance_config,
    get_plugin_settings,
    put_instance_config,
    put_plugin_settings,
)


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_put_instance_config_routes_changes_through_agent_apply_path():
    tenant_id = uuid.uuid4()
    instance_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    inst = types.SimpleNamespace(
        instance_id=instance_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        plugin_id="ark",
        config_json={
            "map": "TheIsland_WP",
            "game_port": 7777,
            "rcon_port": 27020,
            "server_name": "Old Name",
        },
    )
    plugin_catalog = types.SimpleNamespace(plugin_json={"name": "ark"})

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(inst),
            _scalar_result(plugin_catalog),
        ]
    )
    db.add = MagicMock()
    db.flush = AsyncMock()

    body = InstanceConfigBody(
        config_json={
            "map": "TheIsland_WP",
            "game_port": 7779,
            "rcon_port": 27021,
            "server_name": "New Name",
        }
    )

    agent_apply = {
        "status": "success",
        "data": {
            "updated_fields": ["game_port", "rcon_port", "server_name"],
            "apply_result": {
                "status": "success",
                "data": {
                    "ok": True,
                    "warnings": ["INI sync deferred until the server is fully stopped."],
                    "errors": [],
                    "deferred": True,
                },
            },
        },
    }

    with patch("api.routes.settings.is_agent_connected", return_value=True), patch(
        "api.routes.settings.send_command",
        new=AsyncMock(
            side_effect=[
                {"status": "success", "data": {"fields": inst.config_json}},
                agent_apply,
            ]
        ),
    ) as mock_send:
        response = await put_instance_config(
            instance_id=str(instance_id),
            body=body,
            tenant_id=str(tenant_id),
            db=db,
        )

    sent_payload = mock_send.await_args_list[-1].kwargs["payload"]
    assert sent_payload["fields"] == {
        "game_port": 7779,
        "rcon_port": 27021,
        "server_name": "New Name",
    }
    assert response.config_json["game_port"] == 7779
    assert response.apply_result["status"] == "success"
    assert response.apply_result["data"]["deferred"] is True
    assert response.apply_result["data"]["requires_restart"] is True


@pytest.mark.asyncio
async def test_put_instance_config_returns_pending_when_agent_is_offline():
    tenant_id = uuid.uuid4()
    instance_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    inst = types.SimpleNamespace(
        instance_id=instance_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        plugin_id="ark",
        config_json={"map": "TheIsland_WP", "game_port": 7777},
    )

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(inst))
    db.add = MagicMock()
    db.flush = AsyncMock()

    body = InstanceConfigBody(
        config_json={"map": "TheIsland_WP", "game_port": 7779}
    )

    with patch("api.routes.settings.is_agent_connected", return_value=False), patch(
        "api.routes.settings.send_command",
        new=AsyncMock(),
    ) as mock_send:
        response = await put_instance_config(
            instance_id=str(instance_id),
            body=body,
            tenant_id=str(tenant_id),
            db=db,
        )

    mock_send.assert_not_called()
    assert response.apply_result["status"] == "pending"
    assert response.apply_result["data"]["reason"] == "agent_offline"
    assert response.apply_result["data"]["deferred"] is True


@pytest.mark.asyncio
async def test_put_instance_config_materializes_inherited_defaults_and_derived_server_name():
    tenant_id = uuid.uuid4()
    instance_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    inst = types.SimpleNamespace(
        instance_id=instance_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        plugin_id="ark",
        config_json={"map": "TheIsland_WP"},
    )
    plugin_catalog = types.SimpleNamespace(
        plugin_json={
            "display_name": "Brian Cluster",
            "admin_password": "topsecret",
            "rcon_enabled": True,
            "max_players": 19,
            "mods": ["927090"],
            "passive_mods": ["123456"],
            "default_game_port_start": 7777,
            "default_rcon_port_start": 27020,
            "maps": {"TheIsland_WP": {"display_name": "The Island"}},
        }
    )

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(inst),
            _scalar_result(plugin_catalog),
        ]
    )
    db.add = MagicMock()
    db.flush = AsyncMock()

    body = InstanceConfigBody(config_json={"map": "TheIsland_WP"})

    with patch("api.routes.settings.is_agent_connected", return_value=False), patch(
        "api.routes.settings.send_command",
        new=AsyncMock(),
    ):
        response = await put_instance_config(
            instance_id=str(instance_id),
            body=body,
            tenant_id=str(tenant_id),
            db=db,
        )

    assert response.config_json["game_port"] == 7777
    assert response.config_json["rcon_port"] == 27020
    assert response.config_json["admin_password"] == "topsecret"
    assert response.config_json["mods"] == ["927090"]
    assert response.config_json["passive_mods"] == ["123456"]
    assert response.config_json["server_name"] == "Brian Cluster The Island"


@pytest.mark.asyncio
async def test_put_plugin_settings_rejects_non_numeric_cluster_id():
    plugin = types.SimpleNamespace(plugin_id="ark", plugin_json={"name": "ark"})

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(plugin))

    with pytest.raises(HTTPException) as exc_info:
        await put_plugin_settings(
            plugin_name="ark",
            body=PluginSettingsBody(plugin_json={"cluster_id": "657u6565"}),
            tenant_id=str(uuid.uuid4()),
            db=db,
        )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_get_plugin_settings_prefers_host_local_fields_when_agent_is_connected():
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    plugin = types.SimpleNamespace(
        plugin_id="ark",
        plugin_json={"display_name": "Cloud Name", "cluster_id": "1234"},
    )
    agent = types.SimpleNamespace(agent_id=agent_id, tenant_id=tenant_id, is_revoked=False)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(plugin))

    with patch("api.routes.settings._first_connected_agent_for_tenant", new=AsyncMock(return_value=agent)), patch(
        "api.routes.settings.send_command",
        new=AsyncMock(return_value={"status": "success", "data": {"fields": {"display_name": "Local Name"}}}),
    ):
        response = await get_plugin_settings(
            plugin_name="ark",
            tenant_id=str(tenant_id),
            db=db,
        )

    assert response.plugin_json["display_name"] == "Local Name"
    assert response.plugin_json["cluster_id"] == "1234"


@pytest.mark.asyncio
async def test_put_plugin_settings_relays_to_agent_and_keeps_db_mirror():
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    plugin = types.SimpleNamespace(plugin_id="ark", plugin_json={"display_name": "Old"})
    agent = types.SimpleNamespace(agent_id=agent_id, tenant_id=tenant_id, is_revoked=False)

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(plugin))
    db.add = MagicMock()
    db.flush = AsyncMock()

    with patch("api.routes.settings._first_connected_agent_for_tenant", new=AsyncMock(return_value=agent)), patch(
        "api.routes.settings.send_command",
        new=AsyncMock(return_value={"status": "success"}),
    ) as mock_send:
        response = await put_plugin_settings(
            plugin_name="ark",
            body=PluginSettingsBody(plugin_json={"display_name": "New"}),
            tenant_id=str(tenant_id),
            db=db,
        )

    assert mock_send.await_args.kwargs["payload"] == {
        "plugin_name": "ark",
        "fields": {"display_name": "New"},
    }
    assert plugin.plugin_json["display_name"] == "New"
    assert response.plugin_json["display_name"] == "New"


@pytest.mark.asyncio
async def test_get_instance_config_prefers_host_local_fields_when_agent_is_connected():
    tenant_id = uuid.uuid4()
    instance_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    inst = types.SimpleNamespace(
        instance_id=instance_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        plugin_id="ark",
        config_json={"map": "CloudMap_WP"},
    )
    plugin_catalog = types.SimpleNamespace(plugin_json={"display_name": "Brian Cluster"})

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(inst),
            _scalar_result(plugin_catalog),
        ]
    )

    with patch("api.routes.settings.is_agent_connected", return_value=True), patch(
        "api.routes.settings.send_command",
        new=AsyncMock(return_value={"status": "success", "data": {"fields": {"map": "TheIsland_WP"}}}),
    ):
        response = await get_instance_config(
            instance_id=str(instance_id),
            tenant_id=str(tenant_id),
            db=db,
        )

    assert response.config_json["map"] == "TheIsland_WP"
