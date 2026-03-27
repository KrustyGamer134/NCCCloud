from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.agents import is_agent_connected
from core.agent_relay import send_command
from core.tenant import require_tenant
from db.models import Instance, PluginCatalog, TenantSettings
from db.session import get_db

router = APIRouter(tags=["settings"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AppSettingsResponse(BaseModel):
    settings_json: dict


class AppSettingsBody(BaseModel):
    settings_json: dict


class PluginSettingsResponse(BaseModel):
    plugin_id: str
    plugin_json: dict


class PluginSettingsBody(BaseModel):
    plugin_json: dict


class InstanceConfigResponse(BaseModel):
    instance_id: str
    config_json: dict
    apply_result: dict | None = None


class InstanceConfigBody(BaseModel):
    config_json: dict


# ---------------------------------------------------------------------------
# App-level settings (per tenant)
# ---------------------------------------------------------------------------

@router.get("/app", response_model=AppSettingsResponse)
async def get_app_settings(
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> AppSettingsResponse:
    result = await db.execute(
        select(TenantSettings).where(
            TenantSettings.tenant_id == uuid.UUID(tenant_id)
        )
    )
    row = result.scalar_one_or_none()
    return AppSettingsResponse(settings_json=row.settings_json if row else {})


@router.put("/app", response_model=AppSettingsResponse)
async def put_app_settings(
    body: AppSettingsBody,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> AppSettingsResponse:
    result = await db.execute(
        select(TenantSettings).where(
            TenantSettings.tenant_id == uuid.UUID(tenant_id)
        )
    )
    row = result.scalar_one_or_none()

    if row is None:
        row = TenantSettings(
            tenant_id=uuid.UUID(tenant_id),
            settings_json=body.settings_json,
        )
        db.add(row)
    else:
        row.settings_json = body.settings_json
        db.add(row)

    await db.flush()
    return AppSettingsResponse(settings_json=row.settings_json)


# ---------------------------------------------------------------------------
# Plugin-level settings (from/to PluginCatalog.plugin_json)
# ---------------------------------------------------------------------------

@router.get("/plugins/{plugin_name}", response_model=PluginSettingsResponse)
async def get_plugin_settings(
    plugin_name: str,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> PluginSettingsResponse:
    result = await db.execute(
        select(PluginCatalog).where(PluginCatalog.plugin_id == plugin_name)
    )
    plugin = result.scalar_one_or_none()
    if plugin is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Plugin not found", "code": "NOT_FOUND"},
        )
    return PluginSettingsResponse(plugin_id=plugin.plugin_id, plugin_json=plugin.plugin_json)


@router.put("/plugins/{plugin_name}", response_model=PluginSettingsResponse)
async def put_plugin_settings(
    plugin_name: str,
    body: PluginSettingsBody,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> PluginSettingsResponse:
    result = await db.execute(
        select(PluginCatalog).where(PluginCatalog.plugin_id == plugin_name)
    )
    plugin = result.scalar_one_or_none()
    if plugin is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Plugin not found", "code": "NOT_FOUND"},
        )
    existing_json = dict(plugin.plugin_json or {})
    next_json = dict(body.plugin_json or {})
    existing_json.update(next_json)
    plugin.plugin_json = existing_json
    db.add(plugin)
    await db.flush()
    return PluginSettingsResponse(plugin_id=plugin.plugin_id, plugin_json=plugin.plugin_json)


# ---------------------------------------------------------------------------
# Instance-level config (Instance.config_json)
# ---------------------------------------------------------------------------

@router.get("/instances/{instance_id}", response_model=InstanceConfigResponse)
async def get_instance_config(
    instance_id: str,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceConfigResponse:
    result = await db.execute(
        select(Instance).where(
            Instance.instance_id == uuid.UUID(instance_id),
            Instance.tenant_id == uuid.UUID(tenant_id),
        )
    )
    inst = result.scalar_one_or_none()
    if inst is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Instance not found", "code": "NOT_FOUND"},
        )
    return InstanceConfigResponse(
        instance_id=str(inst.instance_id),
        config_json=inst.config_json or {},
    )


@router.put("/instances/{instance_id}", response_model=InstanceConfigResponse)
async def put_instance_config(
    instance_id: str,
    body: InstanceConfigBody,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceConfigResponse:
    result = await db.execute(
        select(Instance).where(
            Instance.instance_id == uuid.UUID(instance_id),
            Instance.tenant_id == uuid.UUID(tenant_id),
        )
    )
    inst = result.scalar_one_or_none()
    if inst is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Instance not found", "code": "NOT_FOUND"},
        )
    previous_config = dict(inst.config_json or {})
    next_config = dict(body.config_json or {})
    inst.config_json = next_config
    db.add(inst)
    await db.flush()

    changed_fields: dict[str, object | None] = {}
    all_keys = set(previous_config) | set(next_config)
    for key in all_keys:
        previous_value = previous_config.get(key)
        next_value = next_config.get(key)
        if previous_value != next_value:
            changed_fields[str(key)] = next_value if key in next_config else None

    apply_result: dict | None = None
    if changed_fields:
        if inst.agent_id is None:
            apply_result = {
                "status": "pending",
                "data": {
                    "applied": False,
                    "deferred": True,
                    "requires_restart": False,
                    "reason": "no_agent",
                    "updated_fields": sorted(changed_fields.keys()),
                    "warnings": ["Config was saved, but no agent is assigned to apply it."],
                },
            }
        else:
            agent_id_str = str(inst.agent_id)
            if not is_agent_connected(agent_id_str):
                apply_result = {
                    "status": "pending",
                    "data": {
                        "applied": False,
                        "deferred": True,
                        "requires_restart": False,
                        "reason": "agent_offline",
                        "updated_fields": sorted(changed_fields.keys()),
                        "warnings": ["Config was saved, but the assigned agent is offline."],
                    },
                }
            else:
                plugin_result = await db.execute(
                    select(PluginCatalog).where(PluginCatalog.plugin_id == inst.plugin_id)
                )
                plugin = plugin_result.scalar_one_or_none()
                plugin_json = plugin.plugin_json if plugin else {}
                agent_result = await send_command(
                    agent_id=agent_id_str,
                    command="set-instance-plugin-config-fields",
                    payload={
                        "instance_id": str(inst.instance_id),
                        "plugin_name": inst.plugin_id,
                        "plugin_json": plugin_json,
                        "fields": changed_fields,
                    },
                )
                apply_data = (
                    agent_result.get("data")
                    if isinstance(agent_result.get("data"), dict)
                    else {}
                )
                sync_result = (
                    apply_data.get("apply_result")
                    if isinstance(apply_data.get("apply_result"), dict)
                    else None
                )
                sync_data = (
                    sync_result.get("data")
                    if isinstance(sync_result, dict) and isinstance(sync_result.get("data"), dict)
                    else {}
                )
                apply_result = {
                    "status": agent_result.get("status", "unknown"),
                    "data": {
                        "applied": agent_result.get("status") == "success" and not bool(sync_data.get("deferred")),
                        "deferred": bool(sync_data.get("deferred")),
                        "requires_restart": bool(sync_data.get("deferred")),
                        "updated_fields": apply_data.get("updated_fields") or sorted(changed_fields.keys()),
                        "warnings": sync_data.get("warnings") or [],
                    },
                }
                if agent_result.get("status") != "success":
                    apply_result["message"] = str(agent_result.get("message") or "Failed to apply config on host")
    else:
        apply_result = {
            "status": "success",
            "data": {
                "applied": True,
                "deferred": False,
                "requires_restart": False,
                "updated_fields": [],
                "warnings": [],
            },
        }

    return InstanceConfigResponse(
        instance_id=str(inst.instance_id),
        config_json=inst.config_json,
        apply_result=apply_result,
    )

