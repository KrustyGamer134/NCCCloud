from __future__ import annotations

import uuid
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.agents import is_agent_connected
from core.agent_relay import send_command
from core.tenant import require_tenant
from db.models import Agent, Instance, PluginCatalog, TenantSettings
from db.session import get_db

router = APIRouter(tags=["settings"])
_AGENT_CLUSTER_CONFIG_FIELDS = {"gameservers_root", "steamcmd_root"}
_CLOUD_APP_SETTINGS_FIELDS = {
    "auto_refresh_enabled",
    "auto_refresh_interval_seconds",
    "max_log_lines_shown",
    "auto_scroll_logs",
    "show_confirmation_dialogs",
}
_INHERITED_INSTANCE_FIELDS = {
    "display_name",
    "cluster_id",
    "mods",
    "passive_mods",
    "admin_password",
    "rcon_enabled",
    "pve",
    "auto_update_on_restart",
    "max_players",
}


def _plugin_value(plugin_json: dict, key: str, *, server_setting: bool = False):
    if key in plugin_json and plugin_json.get(key) is not None:
        return plugin_json.get(key)
    section_name = "server_settings" if server_setting else "app_settings"
    section = plugin_json.get(section_name)
    if isinstance(section, dict):
        entry = section.get(key)
        if isinstance(entry, dict):
            return entry.get("value")
    return None


def _friendly_map_name(plugin_json: dict, map_name: object) -> str:
    raw = str(map_name or "").strip()
    if not raw:
        return ""
    maps = plugin_json.get("maps")
    if isinstance(maps, dict):
        lowered = raw.lower()
        for known_key, entry in maps.items():
            if str(known_key or "").strip().lower() != lowered:
                continue
            if isinstance(entry, dict):
                display_name = str(entry.get("display_name") or "").strip()
                if display_name:
                    return display_name
    text = raw[:-3] if raw.lower().endswith("_wp") else raw
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text.replace("_", " ").strip())
    return " ".join(part[:1].upper() + part[1:] for part in text.split(" ") if part)


def _derived_server_name(plugin_json: dict, config_json: dict) -> str:
    cluster_name = str(_plugin_value(plugin_json, "display_name") or "").strip()
    friendly_map = _friendly_map_name(
        plugin_json,
        config_json.get("map")
        or _plugin_value(plugin_json, "map", server_setting=True),
    )
    if cluster_name and friendly_map:
        return f"{cluster_name} {friendly_map}".strip()
    if friendly_map:
        return friendly_map
    return str(cluster_name or plugin_json.get("display_name") or "").strip()


def _effective_instance_config(config_json: dict, plugin_json: dict) -> dict:
    effective = dict(config_json or {})
    for field in _INHERITED_INSTANCE_FIELDS:
        if field in {"mods", "passive_mods"}:
            if field not in effective:
                value = _plugin_value(plugin_json, field)
                if value is not None:
                    effective[field] = list(value) if isinstance(value, list) else value
            continue
        if field not in effective:
            value = _plugin_value(plugin_json, field)
            if value is not None:
                effective[field] = value

    if "map" not in effective:
        value = _plugin_value(plugin_json, "map", server_setting=True)
        if value is not None:
            effective["map"] = value
    if "game_port" not in effective:
        value = (
            plugin_json.get("default_game_port_start")
            if plugin_json.get("default_game_port_start") is not None
            else _plugin_value(plugin_json, "game_port", server_setting=True)
        )
        if value is not None:
            effective["game_port"] = value
    if "rcon_port" not in effective:
        value = (
            plugin_json.get("default_rcon_port_start")
            if plugin_json.get("default_rcon_port_start") is not None
            else _plugin_value(plugin_json, "rcon_port", server_setting=True)
        )
        if value is not None:
            effective["rcon_port"] = value
    server_name = _derived_server_name(plugin_json, effective)
    if server_name:
        effective["server_name"] = server_name
    return effective


def _materialize_instance_config(previous_config: dict, submitted_config: dict, plugin_json: dict) -> dict:
    materialized = _effective_instance_config(previous_config, plugin_json)
    for key, value in dict(submitted_config or {}).items():
        materialized[str(key)] = value
    explicit_server_name = str(materialized.get("server_name") or "").strip()
    if explicit_server_name:
        materialized["server_name"] = explicit_server_name
    else:
        server_name = _derived_server_name(plugin_json, materialized)
        if server_name:
            materialized["server_name"] = server_name
        else:
            materialized.pop("server_name", None)
    return materialized


def _unwrap_agent_command_result(result: dict) -> tuple[dict, dict]:
    outer = result if isinstance(result, dict) else {}
    inner = outer.get("data") if isinstance(outer.get("data"), dict) else {}
    return outer, inner


def _effective_agent_command_data(result: dict) -> dict:
    _outer, inner = _unwrap_agent_command_result(result)
    nested = inner.get("data") if isinstance(inner.get("data"), dict) else {}
    return nested or inner


async def _connected_agents_for_tenant(tenant_id: str, db: AsyncSession) -> list[Agent]:
    agents_result = await db.execute(
        select(Agent).where(
            Agent.tenant_id == uuid.UUID(tenant_id),
            Agent.is_revoked.is_(False),
        )
    )
    return [agent for agent in agents_result.scalars().all() if is_agent_connected(str(agent.agent_id))]


async def _first_connected_agent_for_tenant(tenant_id: str, db: AsyncSession) -> Agent | None:
    connected = await _connected_agents_for_tenant(tenant_id, db)
    return connected[0] if connected else None


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
    settings_json = dict(row.settings_json or {}) if row else {}

    agent = await _first_connected_agent_for_tenant(tenant_id, db)
    if agent is not None:
        cluster_result = await send_command(
            agent_id=str(agent.agent_id),
            command="get-cluster-config-fields",
            payload={"fields": sorted(_AGENT_CLUSTER_CONFIG_FIELDS)},
        )
        cluster_data = _effective_agent_command_data(cluster_result)
        if cluster_result.get("status") == "success" and isinstance(cluster_data.get("fields"), dict):
            settings_json.update({k: cluster_data["fields"].get(k) for k in _AGENT_CLUSTER_CONFIG_FIELDS})

    return AppSettingsResponse(settings_json=settings_json)


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

    submitted = dict(body.settings_json or {})
    host_fields = {key: submitted.get(key) for key in _AGENT_CLUSTER_CONFIG_FIELDS if key in submitted}
    cloud_fields = {key: value for key, value in submitted.items() if key in _CLOUD_APP_SETTINGS_FIELDS}

    if row is None:
        row = TenantSettings(
            tenant_id=uuid.UUID(tenant_id),
            settings_json={**cloud_fields, **host_fields},
        )
        db.add(row)
    else:
        existing = dict(row.settings_json or {})
        existing.update(host_fields)
        existing.update(cloud_fields)
        row.settings_json = existing
        db.add(row)

    await db.flush()

    if host_fields:
        for agent in await _connected_agents_for_tenant(tenant_id, db):
            await send_command(
                agent_id=str(agent.agent_id),
                command="set-cluster-config-fields",
                payload={"fields": host_fields},
            )

    response_settings = dict(row.settings_json or {})
    response_settings.update(host_fields)
    return AppSettingsResponse(settings_json=response_settings)


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
    plugin_json = dict(plugin.plugin_json or {})
    agent = await _first_connected_agent_for_tenant(tenant_id, db)
    if agent is not None:
        result = await send_command(
            agent_id=str(agent.agent_id),
            command="get-plugin-config-fields",
            payload={"plugin_name": plugin_name},
        )
        effective = _effective_agent_command_data(result)
        if result.get("status") == "success" and isinstance(effective.get("fields"), dict):
            merged = dict(plugin_json)
            merged.update(effective.get("fields") or {})
            plugin_json = merged
    return PluginSettingsResponse(plugin_id=plugin.plugin_id, plugin_json=plugin_json)


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
    cluster_id = body.plugin_json.get("cluster_id")
    if cluster_id is not None and str(cluster_id).strip() and not str(cluster_id).strip().isdigit():
        raise HTTPException(
            status_code=422,
            detail={"error": "Cluster ID must contain digits only", "code": "VALIDATION_ERROR"},
        )
    existing_json = dict(plugin.plugin_json or {})
    next_json = dict(body.plugin_json or {})
    agent = await _first_connected_agent_for_tenant(tenant_id, db)
    if agent is not None:
        await send_command(
            agent_id=str(agent.agent_id),
            command="set-plugin-config-fields",
            payload={"plugin_name": plugin_name, "fields": next_json},
        )
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
    plugin_result = await db.execute(
        select(PluginCatalog).where(PluginCatalog.plugin_id == inst.plugin_id)
    )
    plugin = plugin_result.scalar_one_or_none()
    config_json = dict(inst.config_json or {})
    if inst.agent_id is not None and is_agent_connected(str(inst.agent_id)):
        agent_result = await send_command(
            agent_id=str(inst.agent_id),
            command="get-instance-plugin-config-fields",
            payload={
                "instance_id": str(inst.instance_id),
                "plugin_name": inst.plugin_id,
            },
        )
        effective = _effective_agent_command_data(agent_result)
        if agent_result.get("status") == "success" and isinstance(effective.get("fields"), dict):
            config_json = dict(effective.get("fields") or {})
    effective_config = _effective_instance_config(
        config_json,
        dict(getattr(plugin, "plugin_json", {}) or {}),
    )
    return InstanceConfigResponse(
        instance_id=str(inst.instance_id),
        config_json=effective_config,
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
    plugin_result = await db.execute(
        select(PluginCatalog).where(PluginCatalog.plugin_id == inst.plugin_id)
    )
    plugin = plugin_result.scalar_one_or_none()
    plugin_json = dict(getattr(plugin, "plugin_json", {}) or {})
    if inst.agent_id is not None and is_agent_connected(str(inst.agent_id)):
        agent_current = await send_command(
            agent_id=str(inst.agent_id),
            command="get-instance-plugin-config-fields",
            payload={
                "instance_id": str(inst.instance_id),
                "plugin_name": inst.plugin_id,
            },
        )
        effective_current = _effective_agent_command_data(agent_current)
        if agent_current.get("status") == "success" and isinstance(effective_current.get("fields"), dict):
            previous_config = dict(effective_current.get("fields") or {})
    next_config = _materialize_instance_config(previous_config, dict(body.config_json or {}), plugin_json)
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

