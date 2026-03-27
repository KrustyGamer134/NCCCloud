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

from api.routes.settings import InstanceConfigBody, put_instance_config


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
        new=AsyncMock(return_value=agent_apply),
    ) as mock_send:
        response = await put_instance_config(
            instance_id=str(instance_id),
            body=body,
            tenant_id=str(tenant_id),
            db=db,
        )

    sent_payload = mock_send.await_args.kwargs["payload"]
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
