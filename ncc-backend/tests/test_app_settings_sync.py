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

from api.routes.settings import AppSettingsBody, get_app_settings, put_app_settings


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_result(values):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = list(values)
    result.scalars.return_value = scalars
    return result


@pytest.mark.asyncio
async def test_put_app_settings_syncs_cluster_fields_to_connected_agents():
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    row = types.SimpleNamespace(tenant_id=tenant_id, settings_json={"steamcmd_root": "old"})
    agent = types.SimpleNamespace(agent_id=agent_id, tenant_id=tenant_id, is_revoked=False)

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(row),
            _scalars_result([agent]),
        ]
    )
    db.add = MagicMock()
    db.flush = AsyncMock()

    body = AppSettingsBody(
        settings_json={
            "gameservers_root": r"D:\Ark\BriansPlayground",
            "steamcmd_root": r"D:\Ark\SteamCMD",
            "auto_refresh_enabled": True,
        }
    )

    with patch("api.routes.settings.is_agent_connected", return_value=True), patch(
        "api.routes.settings.send_command",
        new=AsyncMock(return_value={"status": "success"}),
    ) as mock_send:
        response = await put_app_settings(
            body=body,
            tenant_id=str(tenant_id),
            db=db,
        )

    assert response.settings_json["steamcmd_root"] == r"D:\Ark\SteamCMD"
    sent_payload = mock_send.await_args.kwargs["payload"]
    assert sent_payload == {
        "fields": {
            "gameservers_root": r"D:\Ark\BriansPlayground",
            "steamcmd_root": r"D:\Ark\SteamCMD",
        }
    }
    assert row.settings_json == {
        "gameservers_root": r"D:\Ark\BriansPlayground",
        "steamcmd_root": r"D:\Ark\SteamCMD",
        "auto_refresh_enabled": True,
    }


@pytest.mark.asyncio
async def test_put_app_settings_skips_agent_sync_when_no_cluster_fields_present():
    tenant_id = uuid.uuid4()

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_scalar_result(None))
    db.add = MagicMock()
    db.flush = AsyncMock()

    body = AppSettingsBody(
        settings_json={
            "auto_refresh_enabled": True,
            "auto_refresh_interval_seconds": 2,
        }
    )

    with patch("api.routes.settings.send_command", new=AsyncMock()) as mock_send:
        response = await put_app_settings(
            body=body,
            tenant_id=str(tenant_id),
            db=db,
        )

    assert response.settings_json["auto_refresh_enabled"] is True
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_put_app_settings_persists_host_fields_without_connected_agent():
    tenant_id = uuid.uuid4()

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(None),
            _scalars_result([]),
        ]
    )
    db.add = MagicMock()
    db.flush = AsyncMock()

    body = AppSettingsBody(
        settings_json={
            "gameservers_root": r"E:\Arktest",
            "steamcmd_root": r"E:\Arktest\SteamCMD",
        }
    )

    with patch("api.routes.settings.send_command", new=AsyncMock()) as mock_send:
        response = await put_app_settings(
            body=body,
            tenant_id=str(tenant_id),
            db=db,
        )

    assert response.settings_json == {
        "gameservers_root": r"E:\Arktest",
        "steamcmd_root": r"E:\Arktest\SteamCMD",
    }
    created_row = db.add.call_args.args[0]
    assert created_row.settings_json == {
        "gameservers_root": r"E:\Arktest",
        "steamcmd_root": r"E:\Arktest\SteamCMD",
    }
    mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_get_app_settings_merges_host_cluster_fields_from_agent():
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    row = types.SimpleNamespace(
        tenant_id=tenant_id,
        settings_json={
            "auto_refresh_enabled": True,
            "auto_refresh_interval_seconds": 3,
        },
    )
    agent = types.SimpleNamespace(agent_id=agent_id, tenant_id=tenant_id, is_revoked=False)

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _scalar_result(row),
            _scalars_result([agent]),
        ]
    )

    with patch("api.routes.settings.is_agent_connected", return_value=True), patch(
        "api.routes.settings.send_command",
        new=AsyncMock(
            return_value={
                "status": "success",
                "data": {
                    "status": "success",
                    "data": {
                        "fields": {
                            "gameservers_root": r"D:\Ark\Servers",
                            "steamcmd_root": r"D:\Ark\SteamCMD",
                        }
                    },
                },
            }
        ),
    ):
        response = await get_app_settings(
            tenant_id=str(tenant_id),
            db=db,
        )

    assert response.settings_json == {
        "auto_refresh_enabled": True,
        "auto_refresh_interval_seconds": 3,
        "gameservers_root": r"D:\Ark\Servers",
        "steamcmd_root": r"D:\Ark\SteamCMD",
    }
