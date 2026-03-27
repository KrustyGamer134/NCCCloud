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

from api.routes.instances import get_instance_log, get_instance_status


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _instance(*, instance_id: uuid.UUID, tenant_id: uuid.UUID, agent_id: uuid.UUID):
    return types.SimpleNamespace(
        instance_id=instance_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
        plugin_id="ark",
    )


@pytest.mark.asyncio
async def test_get_instance_status_reads_host_reported_snapshot():
    tenant_id = uuid.uuid4()
    instance_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    inst = _instance(instance_id=instance_id, tenant_id=tenant_id, agent_id=agent_id)
    plugin_catalog = types.SimpleNamespace(plugin_json={"name": "ark"})

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_scalar_result(inst), _scalar_result(plugin_catalog)])

    request = types.SimpleNamespace(state=types.SimpleNamespace(user_id="user-1"))

    with patch("api.routes.instances.is_agent_connected", return_value=True), patch(
        "api.routes.instances.send_command",
        new=AsyncMock(return_value={"status": "success", "data": {"state": "STOPPED", "install_status": "NOT_INSTALLED"}}),
    ) as mock_send, patch(
        "api.routes.instances.write_audit_log",
        new=AsyncMock(),
    ):
        response = await get_instance_status(
            str(instance_id),
            request=request,
            tenant_id=str(tenant_id),
            db=db,
        )

    assert response.plugin_id == "ark"
    assert response.status["data"]["state"] == "STOPPED"
    assert response.status["data"]["install_status"] == "NOT_INSTALLED"
    assert mock_send.await_args.kwargs["command"] == "get-status"


@pytest.mark.asyncio
async def test_get_instance_log_reads_host_log_tail():
    tenant_id = uuid.uuid4()
    instance_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    inst = _instance(instance_id=instance_id, tenant_id=tenant_id, agent_id=agent_id)
    plugin_catalog = types.SimpleNamespace(plugin_json={"name": "ark"})

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_scalar_result(inst), _scalar_result(plugin_catalog)])

    request = types.SimpleNamespace(state=types.SimpleNamespace(user_id="user-1"))

    with patch("api.routes.instances.is_agent_connected", return_value=True), patch(
        "api.routes.instances.send_command",
        new=AsyncMock(return_value={"status": "success", "data": {"found": True, "lines": ["a", "b"]}}),
    ) as mock_send, patch(
        "api.routes.instances.write_audit_log",
        new=AsyncMock(),
    ):
        response = await get_instance_log(
            str(instance_id),
            "install_server",
            request=request,
            lines=50,
            tenant_id=str(tenant_id),
            db=db,
        )

    assert response.plugin_id == "ark"
    assert response.log["data"]["found"] is True
    assert response.log["data"]["lines"] == ["a", "b"]
    assert mock_send.await_args.kwargs["command"] == "fetch-logs"
    assert mock_send.await_args.kwargs["payload"]["log_name"] == "install_server"
    assert mock_send.await_args.kwargs["payload"]["lines"] == 50
