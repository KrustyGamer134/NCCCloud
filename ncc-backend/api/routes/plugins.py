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
        )
        for p in available
    ]
