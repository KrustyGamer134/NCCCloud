from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.tenant import require_tenant
from db.models import PluginCatalog, Tenant
from db.session import get_db

router = APIRouter(tags=["plugins"])


class PluginResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    plugin_id: str
    game_system_id: str
    display_name: str
    description: str | None
    available_in_plans: list
    provisioning: dict | None = None


@router.get("", response_model=list[PluginResponse])
async def list_plugins(
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[PluginResponse]:
    result = await db.execute(
        select(Tenant).where(Tenant.tenant_id == uuid.UUID(tenant_id))
    )
    tenant = result.scalar_one_or_none()
    plan = tenant.plan if tenant else "free"

    all_plugins_result = await db.execute(select(PluginCatalog))
    all_plugins = all_plugins_result.scalars().all()

    if plan == "pro":
        available = list(all_plugins)
    else:
        available = [p for p in all_plugins if plan in (p.available_in_plans or [])]

    return [
        PluginResponse(
            plugin_id=p.plugin_id,
            game_system_id=p.plugin_id,
            display_name=p.display_name,
            description=p.description,
            available_in_plans=p.available_in_plans,
            provisioning=_build_provisioning_metadata(p.plugin_json),
        )
        for p in available
    ]


def _build_provisioning_metadata(plugin_json: dict | None) -> dict | None:
    if not isinstance(plugin_json, dict):
        return None

    maps = plugin_json.get("maps")
    if not isinstance(maps, dict) or not maps:
        return None

    default_map = None
    server_settings = plugin_json.get("server_settings")
    if isinstance(server_settings, dict):
        map_setting = server_settings.get("map")
        if isinstance(map_setting, dict):
            raw_default = map_setting.get("value")
            if isinstance(raw_default, str) and raw_default.strip():
                default_map = raw_default.strip()

    map_options = []
    for map_id, metadata in maps.items():
        if not isinstance(map_id, str) or not map_id.strip():
            continue
        display_name = map_id
        if isinstance(metadata, dict):
            raw_display_name = metadata.get("display_name")
            if isinstance(raw_display_name, str) and raw_display_name.strip():
                display_name = raw_display_name.strip()
        map_options.append({"id": map_id, "display_name": display_name})

    if not map_options:
        return None

    return {"default_map": default_map, "maps": map_options}
