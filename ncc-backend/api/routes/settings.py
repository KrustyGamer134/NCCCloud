from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    plugin.plugin_json = body.plugin_json
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
    inst.config_json = body.config_json
    db.add(inst)
    await db.flush()
    return InstanceConfigResponse(
        instance_id=str(inst.instance_id),
        config_json=inst.config_json,
    )
