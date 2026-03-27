from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AuditLog


async def write_audit_log(
    db: AsyncSession,
    tenant_id: str,
    action: str,
    outcome: str,
    user_id: str | None = None,
    agent_id: str | None = None,
    instance_id: str | None = None,
    detail: Any | None = None,
) -> None:
    """Insert a single immutable audit log row. Never updates or deletes."""
    log = AuditLog(
        log_id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant_id) if isinstance(tenant_id, str) else tenant_id,
        user_id=user_id,
        agent_id=uuid.UUID(str(agent_id)) if agent_id else None,
        instance_id=uuid.UUID(str(instance_id)) if instance_id else None,
        action=action,
        outcome=outcome,
        detail_json=detail,
    )
    db.add(log)
    await db.flush()
