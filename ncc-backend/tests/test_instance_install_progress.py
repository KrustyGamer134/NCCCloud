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

from api.routes.instances import get_instance_install_progress


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_get_instance_install_progress_reads_host_install_artifacts():
    tenant_id = uuid.uuid4()
    instance_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    inst = types.SimpleNamespace(
        instance_id=instance_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        plugin_id="ark",
    )
    plugin_catalog = types.SimpleNamespace(plugin_json={"name": "ark"})
    settings_row = types.SimpleNamespace(tenant_id=tenant_id, settings_json={})

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_scalar_result(inst), _scalar_result(plugin_catalog), _scalar_result(settings_row)])
    request = types.SimpleNamespace(state=types.SimpleNamespace(user_id="user-1"))

    progress_payload = {
        "status": "success",
        "data": {
            "state": "running",
            "progress_metadata": {"source": "steamcmd_native_console_log", "start_offset": 12},
            "install_log_found": True,
            "install_log_tail": ["attempt=1"],
            "steamcmd_log_found": True,
            "steamcmd_log_tail": ["Downloading update"],
        },
    }

    with patch("api.routes.instances.is_agent_connected", return_value=True), patch(
        "api.routes.instances.send_command",
        new=AsyncMock(return_value=progress_payload),
    ) as mock_send, patch(
        "api.routes.instances.write_audit_log",
        new=AsyncMock(),
    ):
        response = await get_instance_install_progress(
            str(instance_id),
            request=request,
            lines=25,
            tenant_id=str(tenant_id),
            db=db,
        )

    assert response.plugin_id == "ark"
    assert response.progress["data"]["state"] == "running"
    assert response.progress["data"]["steamcmd_log_tail"] == ["Downloading update"]
    assert mock_send.await_args.kwargs["command"] == "get-install-progress"
    assert mock_send.await_args.kwargs["payload"]["lines"] == 25
