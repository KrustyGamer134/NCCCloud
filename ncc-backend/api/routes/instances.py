from __future__ import annotations

import asyncio
import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

logger = logging.getLogger(__name__)
from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.agents import is_agent_connected
from api.schemas import InstanceResponse
from core.audit import write_audit_log
from core.agent_relay import send_command
from core.plan_limits import check_instance_limit
from core.tenant import require_tenant
from db.models import Agent, Instance, PluginCatalog, Tenant, TenantSettings
from db.session import get_db

router = APIRouter(tags=["instances"])
_TENANT_PLUGIN_DEFAULTS_KEY = "plugin_defaults"


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


def _tenant_plugin_defaults(settings_json: dict | None) -> dict[str, dict]:
    if not isinstance(settings_json, dict):
        return {}
    raw = settings_json.get(_TENANT_PLUGIN_DEFAULTS_KEY)
    if not isinstance(raw, dict):
        return {}
    defaults: dict[str, dict] = {}
    for plugin_id, plugin_json in raw.items():
        if isinstance(plugin_json, dict):
            defaults[str(plugin_id)] = dict(plugin_json)
    return defaults


def _effective_plugin_json(catalog_plugin_json: dict | None, settings_json: dict | None, plugin_id: str) -> dict:
    effective = dict(catalog_plugin_json or {})
    tenant_defaults = _tenant_plugin_defaults(settings_json).get(plugin_id)
    if tenant_defaults:
        effective.update(tenant_defaults)
    return effective


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
        config_json.get("map") or _plugin_value(plugin_json, "map", server_setting=True),
    )
    if cluster_name and friendly_map:
        return f"{cluster_name} {friendly_map}".strip()
    if friendly_map:
        return friendly_map
    return str(cluster_name or plugin_json.get("display_name") or "").strip()


def _effective_instance_config(config_json: dict, plugin_json: dict) -> dict:
    effective = dict(config_json or {})
    for field in ("display_name", "cluster_id", "mods", "passive_mods", "admin_password", "rcon_enabled", "pve", "auto_update_on_restart", "max_players"):
        if field not in effective:
            value = _plugin_value(plugin_json, field)
            if value is not None:
                effective[field] = list(value) if field in {"mods", "passive_mods"} and isinstance(value, list) else value
    if "map" not in effective:
        value = _plugin_value(plugin_json, "map", server_setting=True)
        if value is not None:
            effective["map"] = value
    if "game_port" not in effective:
        value = plugin_json.get("default_game_port_start")
        if value is None:
            value = _plugin_value(plugin_json, "game_port", server_setting=True)
        if value is not None:
            effective["game_port"] = value
    if "rcon_port" not in effective:
        value = plugin_json.get("default_rcon_port_start")
        if value is None:
            value = _plugin_value(plugin_json, "rcon_port", server_setting=True)
        if value is not None:
            effective["rcon_port"] = value
    server_name = _derived_server_name(plugin_json, effective)
    if server_name:
        effective["server_name"] = server_name
    return effective


class CreateInstanceBody(BaseModel):
    plugin_id: str | None = None
    game_system_id: str | None = None
    display_name: str
    agent_id: str | None = None
    config_json: dict | None = None

    @model_validator(mode="after")
    def _validate_identifier(self) -> "CreateInstanceBody":
        resolved = (self.game_system_id or self.plugin_id or "").strip()
        if not resolved:
            raise ValueError("plugin_id or game_system_id is required")
        if self.plugin_id and self.game_system_id and self.plugin_id != self.game_system_id:
            raise ValueError("plugin_id and game_system_id must match when both are provided")
        self.plugin_id = resolved
        self.game_system_id = resolved
        return self


class DiscoverBody(BaseModel):
    agent_id: str | None = None


class InstanceStatusResponse(BaseModel):
    instance_id: str
    game_system_id: str
    plugin_id: str
    status: dict


class InstanceLogResponse(BaseModel):
    instance_id: str
    game_system_id: str
    plugin_id: str
    log: dict


class InstanceInstallProgressResponse(BaseModel):
    instance_id: str
    game_system_id: str
    plugin_id: str
    progress: dict


class InstanceDetailResponse(BaseModel):
    instance: InstanceResponse
    status: dict | None
    install_progress: dict | None
    config_apply: dict | None
    logs: dict


def _unwrap_agent_command_result(result: dict) -> tuple[dict, dict]:
    outer = result if isinstance(result, dict) else {}
    inner = outer.get("data") if isinstance(outer.get("data"), dict) else {}
    return outer, inner


def _effective_agent_command_data(result: dict) -> dict:
    _outer, inner = _unwrap_agent_command_result(result)
    nested = inner.get("data") if isinstance(inner.get("data"), dict) else {}
    return nested or inner


def _raise_agent_command_error(result: dict) -> None:
    outer, inner = _unwrap_agent_command_result(result)
    if outer.get("status") != "success":
        raise HTTPException(status_code=409, detail=outer)
    if inner.get("status") == "error":
        raise HTTPException(status_code=409, detail=inner)


def _agent_read_error_result(command: str, exc: HTTPException) -> dict:
    detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
    code = str(detail.get("code") or "").strip() or "AGENT_READ_FAILED"
    message = str(detail.get("error") or detail.get("message") or "Agent read failed").strip()
    return {
        "status": "error",
        "code": code,
        "message": message,
        "data": {
            "command": command,
            "code": code,
            "message": message,
        },
    }


async def _provision_instance_on_agent(
    *,
    inst: Instance,
    plugin_json: dict,
    request: Request,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    if inst.agent_id is None:
        return {}

    agent_id_str = str(inst.agent_id)
    if not is_agent_connected(agent_id_str):
        raise HTTPException(
            status_code=503,
            detail={"error": "Agent is not connected", "code": "AGENT_OFFLINE"},
        )

    created = await send_command(
        agent_id=agent_id_str,
        command="add-instance",
        payload={
            "instance_id": str(inst.instance_id),
            "plugin_name": inst.plugin_id,
            "game_system_id": inst.plugin_id,
            "plugin_json": plugin_json,
        },
    )
    _raise_agent_command_error(created)

    config_json = _effective_instance_config(dict(inst.config_json or {}), dict(plugin_json or {}))
    map_name = str(config_json.get("map") or config_json.get("map_name") or "").strip()
    if not map_name:
        return config_json

    try:
        game_port = int(config_json.get("game_port") or 0)
    except (TypeError, ValueError):
        game_port = 0
    try:
        rcon_port = int(config_json.get("rcon_port") or 0)
    except (TypeError, ValueError):
        rcon_port = 0

    if game_port <= 0 or rcon_port <= 0:
        allocated = await send_command(
            agent_id=agent_id_str,
            command="allocate-instance-ports",
            payload={
                "plugin_name": inst.plugin_id,
                "game_system_id": inst.plugin_id,
                "plugin_json": plugin_json,
            },
        )
        _raise_agent_command_error(allocated)
        allocated_data = _effective_agent_command_data(allocated)
        try:
            game_port = int(allocated_data.get("game_port") or 0)
            rcon_port = int(allocated_data.get("rcon_port") or 0)
        except (TypeError, ValueError):
            game_port = 0
            rcon_port = 0
        if game_port <= 0 or rcon_port <= 0:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "Failed to allocate instance ports",
                    "code": "PROVISION_FAILED",
                    "raw_result": allocated_data,
                },
            )

    configured = await send_command(
        agent_id=agent_id_str,
        command="configure-instance",
        payload={
            "instance_id": str(inst.instance_id),
            "plugin_name": inst.plugin_id,
            "game_system_id": inst.plugin_id,
            "plugin_json": plugin_json,
            "map_name": map_name,
            "game_port": game_port,
            "rcon_port": rcon_port,
            "mods": config_json.get("mods") or [],
            "passive_mods": config_json.get("passive_mods") or [],
            "map_mod": config_json.get("map_mod"),
        },
    )
    _raise_agent_command_error(configured)

    config_json["map"] = map_name
    config_json["game_port"] = game_port
    config_json["rcon_port"] = rcon_port
    server_name = _derived_server_name(dict(plugin_json or {}), config_json)
    if server_name:
        config_json["server_name"] = server_name
    inst.config_json = config_json
    db.add(inst)

    await write_audit_log(
        db=db,
        tenant_id=tenant_id,
        action="instance.provision",
        outcome="success",
        user_id=getattr(request.state, "user_id", None),
        agent_id=inst.agent_id,
        instance_id=inst.instance_id,
        detail={"plugin_id": inst.plugin_id, "game_system_id": inst.plugin_id},
    )
    return config_json


async def _get_instance(
    instance_id: str, tenant_id: str, db: AsyncSession
) -> Instance:
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
    return inst


async def _action(
    instance_id: str,
    action: str,
    request: Request,
    tenant_id: str,
    db: AsyncSession,
) -> dict:
    inst = await _get_instance(instance_id, tenant_id, db)

    if inst.agent_id is None:
        raise HTTPException(
            status_code=409,
            detail={"error": "No agent assigned to this instance", "code": "NO_AGENT"},
        )

    agent_id_str = str(inst.agent_id)

    if not is_agent_connected(agent_id_str):
        raise HTTPException(
            status_code=503,
            detail={"error": "Agent is not connected", "code": "AGENT_OFFLINE"},
        )

    catalog_result = await db.execute(
        select(PluginCatalog).where(PluginCatalog.plugin_id == inst.plugin_id)
    )
    catalog_row = catalog_result.scalar_one_or_none()
    settings_result = await db.execute(
        select(TenantSettings).where(TenantSettings.tenant_id == uuid.UUID(tenant_id))
    )
    settings_row = settings_result.scalar_one_or_none()
    plugin_json = _effective_plugin_json(
        dict(getattr(catalog_row, "plugin_json", {}) or {}),
        dict(getattr(settings_row, "settings_json", {}) or {}),
        inst.plugin_id,
    )

    result = await send_command(
        agent_id=agent_id_str,
        command=action,
        payload={
            "instance_id": instance_id,
            "plugin_name": inst.plugin_id,
            "game_system_id": inst.plugin_id,
            "plugin_json": plugin_json,
        },
    )

    outcome = result.get("status", "unknown")
    await write_audit_log(
        db=db,
        tenant_id=tenant_id,
        action=f"instance.{action}",
        outcome=outcome,
        user_id=getattr(request.state, "user_id", None),
        agent_id=inst.agent_id,
        instance_id=inst.instance_id,
        detail=result,
    )

    code = result.get("code", "")
    if code == "agent_offline":
        raise HTTPException(status_code=503, detail=result)
    if code == "agent_timeout":
        raise HTTPException(status_code=504, detail=result)

    return result


async def _read_instance_from_agent(
    *,
    inst: Instance,
    command: str,
    payload: dict,
    request: Request,
    tenant_id: str,
    db: AsyncSession,
    plugin_json: dict | None = None,
    audit: bool = True,
) -> dict:
    if inst.agent_id is None:
        raise HTTPException(
            status_code=409,
            detail={"error": "No agent assigned to this instance", "code": "NO_AGENT"},
        )

    agent_id_str = str(inst.agent_id)
    if not is_agent_connected(agent_id_str):
        raise HTTPException(
            status_code=503,
            detail={"error": "Agent is not connected", "code": "AGENT_OFFLINE"},
        )

    resolved_plugin_json = plugin_json
    if resolved_plugin_json is None:
        catalog_result = await db.execute(
            select(PluginCatalog).where(PluginCatalog.plugin_id == inst.plugin_id)
        )
        catalog_row = catalog_result.scalar_one_or_none()
        settings_result = await db.execute(
            select(TenantSettings).where(TenantSettings.tenant_id == inst.tenant_id)
        )
        settings_row = settings_result.scalar_one_or_none()
        resolved_plugin_json = _effective_plugin_json(
            dict(getattr(catalog_row, "plugin_json", {}) or {}),
            dict(getattr(settings_row, "settings_json", {}) or {}),
            inst.plugin_id,
        )

    result = await send_command(
        agent_id=agent_id_str,
        command=command,
        payload={
            "instance_id": str(inst.instance_id),
            "plugin_name": inst.plugin_id,
            "game_system_id": inst.plugin_id,
            "plugin_json": resolved_plugin_json,
            **dict(payload or {}),
        },
    )

    if audit:
        await write_audit_log(
            db=db,
            tenant_id=tenant_id,
            action=f"instance.read.{command}",
            outcome=result.get("status", "unknown"),
            user_id=getattr(request.state, "user_id", None),
            agent_id=inst.agent_id,
            instance_id=inst.instance_id,
            detail=result,
        )

    code = result.get("code", "")
    if code == "agent_offline":
        raise HTTPException(status_code=503, detail=result)
    if code == "agent_timeout":
        raise HTTPException(status_code=504, detail=result)

    return result


async def _safe_agent_read(
    *,
    inst: Instance,
    command: str,
    payload: dict,
    request: Request,
    tenant_id: str,
    db: AsyncSession,
    plugin_json: dict | None = None,
    audit: bool = True,
) -> dict | None:
    if inst.agent_id is None:
        return _agent_read_error_result(
            command,
            HTTPException(status_code=409, detail={"error": "No agent assigned to this instance", "code": "NO_AGENT"}),
        )
    agent_id_str = str(inst.agent_id)
    if not is_agent_connected(agent_id_str):
        return _agent_read_error_result(
            command,
            HTTPException(status_code=503, detail={"error": "Agent is not connected", "code": "AGENT_OFFLINE"}),
        )
    try:
        return await _read_instance_from_agent(
            inst=inst,
            command=command,
            payload=payload,
            request=request,
            tenant_id=tenant_id,
            db=db,
            plugin_json=plugin_json,
            audit=audit,
        )
    except HTTPException as exc:
        return _agent_read_error_result(command, exc)


@router.get("", response_model=list[InstanceResponse])
async def list_instances(
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[InstanceResponse]:
    result = await db.execute(
        select(Instance).where(Instance.tenant_id == uuid.UUID(tenant_id))
    )
    instances = result.scalars().all()
    plugin_ids = sorted({str(instance.plugin_id) for instance in instances})
    plugin_rows: dict[str, dict] = {}
    if plugin_ids:
        plugin_result = await db.execute(
            select(PluginCatalog).where(PluginCatalog.plugin_id.in_(plugin_ids))
        )
        plugin_rows = {row.plugin_id: dict(row.plugin_json or {}) for row in plugin_result.scalars().all()}
    settings_result = await db.execute(
        select(TenantSettings).where(TenantSettings.tenant_id == uuid.UUID(tenant_id))
    )
    settings_row = settings_result.scalar_one_or_none()
    settings_json = dict(getattr(settings_row, "settings_json", {}) or {})
    responses: list[InstanceResponse] = []
    for instance in instances:
        instance.config_json = _effective_instance_config(
            dict(instance.config_json or {}),
            _effective_plugin_json(
                plugin_rows.get(instance.plugin_id, {}),
                settings_json,
                instance.plugin_id,
            ),
        )
        responses.append(InstanceResponse.from_orm_safe(instance))
    return responses


@router.get("/{instance_id}", response_model=InstanceResponse)
async def get_instance(
    instance_id: str,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceResponse:
    inst = await _get_instance(instance_id, tenant_id, db)
    plugin_result = await db.execute(
        select(PluginCatalog).where(PluginCatalog.plugin_id == inst.plugin_id)
    )
    plugin = plugin_result.scalar_one_or_none()
    settings_result = await db.execute(
        select(TenantSettings).where(TenantSettings.tenant_id == uuid.UUID(tenant_id))
    )
    settings_row = settings_result.scalar_one_or_none()
    plugin_json = _effective_plugin_json(
        dict(getattr(plugin, "plugin_json", {}) or {}),
        dict(getattr(settings_row, "settings_json", {}) or {}),
        inst.plugin_id,
    )
    inst.config_json = _effective_instance_config(
        dict(inst.config_json or {}),
        plugin_json,
    )
    return InstanceResponse.from_orm_safe(inst)


@router.get("/{instance_id}/detail", response_model=InstanceDetailResponse)
async def get_instance_detail(
    instance_id: str,
    request: Request,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceDetailResponse:
    inst = await _get_instance(instance_id, tenant_id, db)
    plugin_result = await db.execute(
        select(PluginCatalog).where(PluginCatalog.plugin_id == inst.plugin_id)
    )
    plugin = plugin_result.scalar_one_or_none()
    settings_result = await db.execute(
        select(TenantSettings).where(TenantSettings.tenant_id == uuid.UUID(tenant_id))
    )
    settings_row = settings_result.scalar_one_or_none()
    plugin_json = _effective_plugin_json(
        dict(getattr(plugin, "plugin_json", {}) or {}),
        dict(getattr(settings_row, "settings_json", {}) or {}),
        inst.plugin_id,
    )
    inst.config_json = _effective_instance_config(
        dict(inst.config_json or {}),
        plugin_json,
    )
    pending_ini_sync_fields = [
        str(item).strip()
        for item in list((inst.config_json or {}).get("_pending_ini_sync_fields") or [])
        if str(item).strip()
    ]

    status, install_progress, install_log, steamcmd_log, runtime_log = await asyncio.gather(
        _safe_agent_read(
            inst=inst,
            command="get-status",
            payload={},
            request=request,
            tenant_id=tenant_id,
            db=db,
            plugin_json=plugin_json,
            audit=False,
        ),
        _safe_agent_read(
            inst=inst,
            command="get-install-progress",
            payload={"lines": 50},
            request=request,
            tenant_id=tenant_id,
            db=db,
            plugin_json=plugin_json,
            audit=False,
        ),
        _safe_agent_read(
            inst=inst,
            command="fetch-logs",
            payload={"log_name": "install_server", "lines": 50},
            request=request,
            tenant_id=tenant_id,
            db=db,
            plugin_json=plugin_json,
            audit=False,
        ),
        _safe_agent_read(
            inst=inst,
            command="fetch-logs",
            payload={"log_name": "steamcmd_install", "lines": 50},
            request=request,
            tenant_id=tenant_id,
            db=db,
            plugin_json=plugin_json,
            audit=False,
        ),
        _safe_agent_read(
            inst=inst,
            command="fetch-logs",
            payload={"log_name": "server", "lines": 50},
            request=request,
            tenant_id=tenant_id,
            db=db,
            plugin_json=plugin_json,
            audit=False,
        ),
    )

    return InstanceDetailResponse(
        instance=InstanceResponse.from_orm_safe(inst),
        status=status,
        install_progress=install_progress,
        config_apply={
            "status": "deferred" if pending_ini_sync_fields else "applied",
            "data": {
                "requires_restart": bool(pending_ini_sync_fields),
                "pending_fields": pending_ini_sync_fields,
            },
        },
        logs={
            "install_server": install_log,
            "steamcmd_install": steamcmd_log,
            "server": runtime_log,
        },
    )


@router.get("/{instance_id}/status", response_model=InstanceStatusResponse)
async def get_instance_status(
    instance_id: str,
    request: Request,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceStatusResponse:
    inst = await _get_instance(instance_id, tenant_id, db)
    result = await _read_instance_from_agent(
        inst=inst,
        command="get-status",
        payload={},
        request=request,
        tenant_id=tenant_id,
        db=db,
    )
    return InstanceStatusResponse(
        instance_id=str(inst.instance_id),
        game_system_id=inst.plugin_id,
        plugin_id=inst.plugin_id,
        status=result,
    )


@router.get("/{instance_id}/logs/{log_name}", response_model=InstanceLogResponse)
async def get_instance_log(
    instance_id: str,
    log_name: str,
    request: Request,
    lines: int = 200,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceLogResponse:
    inst = await _get_instance(instance_id, tenant_id, db)
    result = await _read_instance_from_agent(
        inst=inst,
        command="fetch-logs",
        payload={"log_name": str(log_name), "lines": int(lines)},
        request=request,
        tenant_id=tenant_id,
        db=db,
    )
    return InstanceLogResponse(
        instance_id=str(inst.instance_id),
        game_system_id=inst.plugin_id,
        plugin_id=inst.plugin_id,
        log=result,
    )


@router.get("/{instance_id}/install-progress", response_model=InstanceInstallProgressResponse)
async def get_instance_install_progress(
    instance_id: str,
    request: Request,
    lines: int = 50,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceInstallProgressResponse:
    inst = await _get_instance(instance_id, tenant_id, db)
    result = await _read_instance_from_agent(
        inst=inst,
        command="get-install-progress",
        payload={"lines": int(lines)},
        request=request,
        tenant_id=tenant_id,
        db=db,
    )
    return InstanceInstallProgressResponse(
        instance_id=str(inst.instance_id),
        game_system_id=inst.plugin_id,
        plugin_id=inst.plugin_id,
        progress=result,
    )


@router.post("", response_model=InstanceResponse, status_code=201)
async def create_instance(
    body: CreateInstanceBody,
    request: Request,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceResponse:
    tenant_result = await db.execute(
        select(Tenant).where(Tenant.tenant_id == uuid.UUID(tenant_id))
    )
    tenant = tenant_result.scalar_one_or_none()
    plan = tenant.plan if tenant else "free"
    await check_instance_limit(db, tenant_id, plan)

    config_json = dict(body.config_json or {})
    if body.plugin_id == "ark_survival_ascended":
        fallback_map = str(config_json.get("map") or "").strip()
        if not fallback_map:
            fallback_map = body.display_name.strip()
        if fallback_map:
            config_json["map"] = fallback_map

    inst = Instance(
        instance_id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant_id),
        agent_id=uuid.UUID(body.agent_id) if body.agent_id else None,
        plugin_id=body.plugin_id,
        display_name=body.display_name,
        config_json=config_json,
        status="unknown",
        install_status="not_installed",
    )
    db.add(inst)
    await db.flush()

    catalog_result = await db.execute(
        select(PluginCatalog).where(PluginCatalog.plugin_id == inst.plugin_id)
    )
    catalog_row = catalog_result.scalar_one_or_none()
    settings_result = await db.execute(
        select(TenantSettings).where(TenantSettings.tenant_id == uuid.UUID(tenant_id))
    )
    settings_row = settings_result.scalar_one_or_none()
    plugin_json = _effective_plugin_json(
        dict(getattr(catalog_row, "plugin_json", {}) or {}),
        dict(getattr(settings_row, "settings_json", {}) or {}),
        inst.plugin_id,
    )

    inst.config_json = await _provision_instance_on_agent(
        inst=inst,
        plugin_json=plugin_json,
        request=request,
        tenant_id=tenant_id,
        db=db,
    ) or inst.config_json
    db.add(inst)
    await db.flush()

    await write_audit_log(
        db=db,
        tenant_id=tenant_id,
        action="instance.create",
        outcome="success",
        user_id=getattr(request.state, "user_id", None),
        instance_id=inst.instance_id,
        detail={"plugin_id": body.plugin_id, "game_system_id": body.game_system_id, "display_name": body.display_name},
    )

    return InstanceResponse.from_orm_safe(inst)


@router.post("/discover")
async def discover_instances(
    body: DiscoverBody,
    request: Request,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings_result = await db.execute(
        select(TenantSettings).where(TenantSettings.tenant_id == uuid.UUID(tenant_id))
    )
    settings_row = settings_result.scalar_one_or_none()
    gameservers_root: str = ""
    if settings_row and settings_row.settings_json:
        gameservers_root = settings_row.settings_json.get("gameservers_root", "")

    logger.debug(
        "discover: tenant_id=%s settings_json=%r gameservers_root=%r",
        tenant_id,
        settings_row.settings_json if settings_row else None,
        gameservers_root,
    )

    agent_id_str = body.agent_id
    if not agent_id_str:
        agents_result = await db.execute(
            select(Agent).where(
                Agent.tenant_id == uuid.UUID(tenant_id),
                Agent.is_revoked.is_(False),
            )
        )
        for a in agents_result.scalars().all():
            if is_agent_connected(str(a.agent_id)):
                agent_id_str = str(a.agent_id)
                break

    if not agent_id_str:
        raise HTTPException(
            status_code=503,
            detail={"error": "No connected agent available", "code": "AGENT_OFFLINE"},
        )

    result = await send_command(
        agent_id=agent_id_str,
        command="discover",
        payload={"gameservers_root": gameservers_root},
    )

    await write_audit_log(
        db=db,
        tenant_id=tenant_id,
        action="instance.discover",
        outcome=result.get("status", "unknown"),
        user_id=getattr(request.state, "user_id", None),
        detail={"gameservers_root": gameservers_root, "agent_id": agent_id_str},
    )

    return result


@router.delete("/{instance_id}", status_code=200)
async def delete_instance(
    instance_id: str,
    request: Request,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    inst = await _get_instance(instance_id, tenant_id, db)

    await write_audit_log(
        db=db,
        tenant_id=tenant_id,
        action="instance.delete",
        outcome="success",
        user_id=getattr(request.state, "user_id", None),
        instance_id=inst.instance_id,
        detail={"plugin_id": inst.plugin_id, "game_system_id": inst.plugin_id, "display_name": inst.display_name},
    )

    await db.delete(inst)
    await db.flush()


@router.post("/{instance_id}/start")
async def start_instance(
    instance_id: str,
    request: Request,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _action(instance_id, "start", request, tenant_id, db)


@router.post("/{instance_id}/stop")
async def stop_instance(
    instance_id: str,
    request: Request,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _action(instance_id, "stop", request, tenant_id, db)


@router.post("/{instance_id}/restart")
async def restart_instance(
    instance_id: str,
    request: Request,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _action(instance_id, "restart", request, tenant_id, db)


@router.post("/{instance_id}/update")
async def update_instance(
    instance_id: str,
    request: Request,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _action(instance_id, "update", request, tenant_id, db)


@router.post("/{instance_id}/install-deps")
async def install_deps(
    instance_id: str,
    request: Request,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _action(instance_id, "install-deps", request, tenant_id, db)


@router.post("/{instance_id}/install-server")
async def install_server(
    instance_id: str,
    request: Request,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _action(instance_id, "install-server", request, tenant_id, db)

