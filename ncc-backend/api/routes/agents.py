from __future__ import annotations

import secrets
import uuid

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.audit import write_audit_log
from core.plan_limits import check_agent_limit
from core.settings import settings
from core.tenant import require_tenant
from db.models import Agent, Tenant
from db.session import get_db

router = APIRouter(tags=["agents"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agent_id: str
    tenant_id: str
    machine_name: str
    agent_version: str | None
    public_ip: str | None
    last_seen: str | None
    is_revoked: bool
    is_connected: bool
    created_at: str

    @classmethod
    def from_orm_safe(cls, agent: Agent) -> "AgentResponse":
        agent_id_str = str(agent.agent_id)
        return cls(
            agent_id=agent_id_str,
            tenant_id=str(agent.tenant_id),
            machine_name=agent.machine_name,
            agent_version=agent.agent_version,
            public_ip=agent.public_ip,
            last_seen=agent.last_seen.isoformat() if agent.last_seen else None,
            is_revoked=agent.is_revoked,
            is_connected=is_agent_connected(agent_id_str),
            created_at=agent.created_at.isoformat() if agent.created_at else "",
        )


class RegisterAgentBody(BaseModel):
    machine_name: str
    # Required when registering via bootstrap key (agent self-registration).
    # Not needed when a Clerk-authenticated user registers via the frontend.
    tenant_id: str | None = None


class RegisterAgentResponse(BaseModel):
    agent_id: str
    api_key: str
    machine_name: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _generate_api_key() -> tuple[str, str]:
    """Return (plaintext_key, bcrypt_hash)."""
    key = secrets.token_hex(32)
    hashed = bcrypt.hashpw(key.encode(), bcrypt.gensalt()).decode()
    return key, hashed


async def _get_agent_for_tenant(
    agent_id: str, tenant_id: str, db: AsyncSession
) -> Agent:
    result = await db.execute(
        select(Agent).where(
            Agent.agent_id == uuid.UUID(agent_id),
            Agent.tenant_id == uuid.UUID(tenant_id),
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail={"error": "Agent not found", "code": "NOT_FOUND"})
    return agent


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("", response_model=list[AgentResponse])
async def list_agents(
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[AgentResponse]:
    result = await db.execute(
        select(Agent).where(Agent.tenant_id == uuid.UUID(tenant_id))
    )
    agents = result.scalars().all()
    return [AgentResponse.from_orm_safe(a) for a in agents]


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    agent = await _get_agent_for_tenant(agent_id, tenant_id, db)
    return AgentResponse.from_orm_safe(agent)


@router.post("/register", response_model=RegisterAgentResponse, status_code=201)
async def register_agent(
    body: RegisterAgentBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RegisterAgentResponse:
    """
    Register a new agent.

    Two auth paths:
      1. Clerk JWT (frontend user) — middleware already ran and set
         request.state.tenant_id.  body.tenant_id is ignored.
      2. Bootstrap key (agent self-registration) — /agents/register is in
         _SKIP_PATHS so the middleware did not run.  The caller must supply
         Authorization: Bearer <BOOTSTRAP_API_KEY> and body.tenant_id.
    """
    # --- Resolve tenant_id -----------------------------------------------
    tenant_id: str | None = getattr(request.state, "tenant_id", None)

    if tenant_id is None:
        # Bootstrap path: validate key and use tenant_id from request body.
        auth_header = request.headers.get("Authorization", "")
        provided_key = auth_header[len("Bearer "):] if auth_header.startswith("Bearer ") else ""
        if not settings.bootstrap_api_key or provided_key != settings.bootstrap_api_key:
            raise HTTPException(
                status_code=401,
                detail={"error": "Invalid or missing bootstrap key", "code": "UNAUTHORIZED"},
            )
        if not body.tenant_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "tenant_id is required when registering with a bootstrap key",
                    "code": "MISSING_TENANT",
                },
            )
        # Validate that it looks like a UUID before we pass it to the DB.
        try:
            uuid.UUID(body.tenant_id)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"error": "tenant_id is not a valid UUID", "code": "INVALID_TENANT"},
            )
        tenant_id = body.tenant_id

    # --- Enforce plan agent limit ----------------------------------------
    tenant_result = await db.execute(
        select(Tenant).where(Tenant.tenant_id == uuid.UUID(tenant_id))
    )
    tenant = tenant_result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "Tenant not found", "code": "NOT_FOUND"},
        )
    plan = tenant.plan
    await check_agent_limit(db, tenant_id, plan)

    api_key, api_key_hash = _generate_api_key()

    agent = Agent(
        agent_id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant_id),
        machine_name=body.machine_name,
        api_key_hash=api_key_hash,
        is_revoked=False,
    )
    db.add(agent)
    await db.flush()

    await write_audit_log(
        db=db,
        tenant_id=tenant_id,
        action="agent.register",
        outcome="success",
        user_id=getattr(request.state, "user_id", None),
        agent_id=agent.agent_id,
        detail={"machine_name": body.machine_name},
    )

    return RegisterAgentResponse(
        agent_id=str(agent.agent_id),
        api_key=api_key,
        machine_name=agent.machine_name,
    )


def is_agent_connected(agent_id: str) -> bool:
    """Return True if the agent currently has an active WebSocket connection."""
    # Late import — agent_ws is not a hard dependency of this module at import time.
    from api.agent_ws import _agent_connections

    return agent_id in _agent_connections


@router.delete("/{agent_id}/key", response_model=RegisterAgentResponse)
async def rotate_agent_key(
    agent_id: str,
    request: Request,
    tenant_id: str = Depends(require_tenant),
    db: AsyncSession = Depends(get_db),
) -> RegisterAgentResponse:
    agent = await _get_agent_for_tenant(agent_id, tenant_id, db)

    api_key, api_key_hash = _generate_api_key()
    agent.api_key_hash = api_key_hash
    agent.is_revoked = False
    db.add(agent)
    await db.flush()

    await write_audit_log(
        db=db,
        tenant_id=tenant_id,
        action="agent.rotate_key",
        outcome="success",
        user_id=getattr(request.state, "user_id", None),
        agent_id=agent.agent_id,
        detail={"machine_name": agent.machine_name},
    )

    return RegisterAgentResponse(
        agent_id=str(agent.agent_id),
        api_key=api_key,
        machine_name=agent.machine_name,
    )
