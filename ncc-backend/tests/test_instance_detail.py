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

from api.routes.instances import get_instance_detail


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_get_instance_detail_composes_status_progress_and_logs():
    tenant_id = uuid.uuid4()
    instance_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    inst = types.SimpleNamespace(
        instance_id=instance_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        plugin_id="ark",
        display_name="Ark Test",
        config_json={"map": "TheIsland_WP", "_pending_ini_sync_fields": ["server_name", "mods"]},
        status="unknown",
        install_status="not_installed",
        agent_last_seen=None,
        created_at=None,
    )
    plugin_catalog = types.SimpleNamespace(plugin_json={"name": "ark"})
    settings_row = types.SimpleNamespace(tenant_id=tenant_id, settings_json={})

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(inst),
            _scalar_result(plugin_catalog),
            _scalar_result(settings_row),
            _scalar_result(plugin_catalog),
            _scalar_result(settings_row),
            _scalar_result(plugin_catalog),
            _scalar_result(settings_row),
            _scalar_result(plugin_catalog),
            _scalar_result(settings_row),
            _scalar_result(plugin_catalog),
            _scalar_result(settings_row),
            _scalar_result(plugin_catalog),
            _scalar_result(settings_row),
        ]
    )
    request = types.SimpleNamespace(state=types.SimpleNamespace(user_id="user-1"))

    send_results = [
        {"status": "success", "data": {"state": "STOPPED", "install_status": "NOT_INSTALLED"}},
        {
            "status": "success",
            "data": {
                "state": "validating",
                "steamcmd_progress": {"phase": "validating", "percent": 14.69, "completed": False},
            },
        },
        {"status": "success", "data": {"found": True, "lines": ["install line"]}},
        {"status": "success", "data": {"found": True, "lines": ["Update state (0x81) verifying update, progress: 14.69 (1924301314 / 13098544774)"]}},
        {"status": "success", "data": {"found": True, "lines": ["runtime line"]}},
    ]

    with patch("api.routes.instances.is_agent_connected", return_value=True), patch(
        "api.routes.instances.send_command",
        new=AsyncMock(side_effect=send_results),
    ) as mock_send, patch(
        "api.routes.instances.write_audit_log",
        new=AsyncMock(),
    ), patch(
        "api.routes.agents.is_agent_connected", return_value=True
    ):
        response = await get_instance_detail(
            str(instance_id),
            request=request,
            tenant_id=str(tenant_id),
            db=db,
        )

    assert response.instance.plugin_id == "ark"
    assert response.status["data"]["state"] == "STOPPED"
    assert response.install_progress["data"]["state"] == "validating"
    assert response.install_progress["data"]["steamcmd_progress"]["percent"] == 14.69
    assert response.config_apply["status"] == "deferred"
    assert response.config_apply["data"]["requires_restart"] is True
    assert response.config_apply["data"]["pending_fields"] == ["server_name", "mods"]
    assert response.logs["install_server"]["data"]["lines"] == ["install line"]
    assert response.logs["steamcmd_install"]["data"]["lines"] == [
        "Update state (0x81) verifying update, progress: 14.69 (1924301314 / 13098544774)"
    ]
    assert response.logs["server"]["data"]["lines"] == ["runtime line"]
    commands = [call.kwargs["command"] for call in mock_send.await_args_list]
    assert commands == ["get-status", "get-install-progress", "fetch-logs", "fetch-logs", "fetch-logs"]


@pytest.mark.asyncio
async def test_get_instance_detail_preserves_section_errors():
    tenant_id = uuid.uuid4()
    instance_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    inst = types.SimpleNamespace(
        instance_id=instance_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        plugin_id="ark",
        display_name="Ark Test",
        config_json={"map": "TheIsland_WP"},
        status="unknown",
        install_status="not_installed",
        agent_last_seen=None,
        created_at=None,
    )
    plugin_catalog = types.SimpleNamespace(plugin_json={"name": "ark"})
    settings_row = types.SimpleNamespace(tenant_id=tenant_id, settings_json={})

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(inst),
            _scalar_result(plugin_catalog),
            _scalar_result(settings_row),
        ]
    )
    request = types.SimpleNamespace(state=types.SimpleNamespace(user_id="user-1"))

    with patch("api.routes.instances.is_agent_connected", return_value=False), patch(
        "api.routes.agents.is_agent_connected", return_value=False
    ):
        response = await get_instance_detail(
            str(instance_id),
            request=request,
            tenant_id=str(tenant_id),
            db=db,
        )

    assert response.status["status"] == "error"
    assert response.status["code"] == "AGENT_OFFLINE"
    assert response.install_progress["status"] == "error"
    assert response.logs["install_server"]["status"] == "error"
