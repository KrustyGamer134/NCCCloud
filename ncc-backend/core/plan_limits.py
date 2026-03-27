"""
Plan-level resource limits — BILL-001.

Centralises every "can this tenant do X?" check so route handlers stay clean.
All check_* functions accept an already-open AsyncSession from the caller so
they participate in the same unit-of-work and never open a second transaction.

Limit values
------------
max_instances / max_agents : int  — hard ceiling; None means unlimited
plugins                    : list[str] | None — allowed game_ids; None means all
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Agent, Instance

# ---------------------------------------------------------------------------
# Plan definitions
# ---------------------------------------------------------------------------
PLAN_LIMITS: dict[str, dict] = {
    "free": {
        "max_instances": 1,
        "max_agents": 1,
        "plugins": ["ark_survival_ascended"],
    },
    "basic": {
        "max_instances": 3,
        "max_agents": 2,
        "plugins": None,   # all plugins
    },
    "pro": {
        "max_instances": None,  # unlimited
        "max_agents": None,     # unlimited
        "plugins": None,        # all plugins
    },
}

_FALLBACK_PLAN = "free"


def get_limits(plan: str) -> dict:
    """
    Return the limit dict for *plan*.

    Falls back to 'free' limits for any unrecognised plan string so that
    unknown plans never silently bypass restrictions.
    """
    return PLAN_LIMITS.get(plan, PLAN_LIMITS[_FALLBACK_PLAN])


# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------

async def check_instance_limit(
    db: AsyncSession, tenant_id: str, plan: str
) -> None:
    """
    Raise HTTPException(402) if the tenant has reached its instance ceiling.

    Counts all instances (regardless of status) because the limit applies to
    provisioned slots, not running ones.
    """
    limits = get_limits(plan)
    max_instances: int | None = limits["max_instances"]
    if max_instances is None:
        return  # unlimited plan — skip the query entirely

    result = await db.execute(
        select(func.count())
        .select_from(Instance)
        .where(Instance.tenant_id == uuid.UUID(tenant_id))
    )
    current: int = result.scalar_one()

    if current >= max_instances:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "plan_limit_reached",
                "code": "plan_limit_reached",
                "limit_type": "instances",
                "current": current,
                "max": max_instances,
            },
        )


async def check_agent_limit(
    db: AsyncSession, tenant_id: str, plan: str
) -> None:
    """
    Raise HTTPException(402) if the tenant has reached its agent ceiling.

    Only non-revoked agents count: a revoked agent slot is considered freed.
    """
    limits = get_limits(plan)
    max_agents: int | None = limits["max_agents"]
    if max_agents is None:
        return  # unlimited plan

    result = await db.execute(
        select(func.count())
        .select_from(Agent)
        .where(
            Agent.tenant_id == uuid.UUID(tenant_id),
            Agent.is_revoked.is_(False),
        )
    )
    current: int = result.scalar_one()

    if current >= max_agents:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "plan_limit_reached",
                "code": "plan_limit_reached",
                "limit_type": "agents",
                "current": current,
                "max": max_agents,
            },
        )
