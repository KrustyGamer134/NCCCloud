from __future__ import annotations

import logging
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
    if created.get("status") != "success":
        raise HTTPException(status_code=409, detail=created)

    config_json = dict(inst.config_json or {})
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
        if allocated.get("status") != "success":
            raise HTTPException(status_code=409, detail=allocated)
        allocated_data = allocated.get("data") if isinstance(allocated.get("data"), dict) else {}
        try:
            game_port = int(allocated_data.get("game_port") or 0)
            rcon_port = int(allocated_data.get("rcon_port") or 0)
        except (TypeError, ValueError):
            game_port = 0
            rcon_port = 0
        if game_port <= 0 or rcon_port <= 0:
            raise HTTPException(
                status_code=409,
                detail={"error": "Failed to allocate instance ports", "code": "PROVISION_FAILED"},
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
    if configured.get("status") != "success":
        raise HTTPException(status_code=409, detail=configured)

    config_json["map"] = map_name
    config_json["game_port"] = game_port
    config_json["rcon_port"] = rcon_port
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
    plugin_json = catalog_row.plugin_json if catalog_row else {}

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


@router.get("", response_model=list[InstanceResponse])
async def list_instances(
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[InstanceResponse]:
    result = await db.execute(
        select(Instance).where(Instance.tenant_id == uuid.UUID(tenant_id))
    )
    instances = result.scalars().all()
    return [InstanceResponse.from_orm_safe(i) for i in instances]


@router.get("/{instance_id}", response_model=InstanceResponse)
async def get_instance(
    instance_id: str,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> InstanceResponse:
    inst = await _get_instance(instance_id, tenant_id, db)
    return InstanceResponse.from_orm_safe(inst)


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

    inst = Instance(
        instance_id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant_id),
        agent_id=uuid.UUID(body.agent_id) if body.agent_id else None,
        plugin_id=body.plugin_id,
        display_name=body.display_name,
        config_json=body.config_json or {},
        status="unknown",
        install_status="not_installed",
    )
    db.add(inst)
    await db.flush()

    catalog_result = await db.execute(
        select(PluginCatalog).where(PluginCatalog.plugin_id == inst.plugin_id)
    )
    catalog_row = catalog_result.scalar_one_or_none()
    plugin_json = catalog_row.plugin_json if catalog_row else {}

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
