"""Add composite performance indexes

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-24 00:00:00.000000

Adds four composite indexes that cover the most common multi-column query
patterns:

  instances  (tenant_id, status)      — status-filtered list views per tenant
  instances  (tenant_id, agent_id)    — agent-scoped instance lookups per tenant
  audit_logs (tenant_id, created_at)  — time-ordered audit feeds per tenant (DESC reads)
  agents     (tenant_id, is_revoked)  — active-agent listings per tenant

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # instances: status-filtered listing per tenant
    op.create_index(
        "ix_instances_tenant_status",
        "instances",
        ["tenant_id", "status"],
    )

    # instances: agent-scoped lookup per tenant
    # (Note: 0001 already has single-column ix_instances_agent_id; this
    # composite covers queries that filter on *both* tenant_id and agent_id.)
    op.create_index(
        "ix_instances_tenant_agent_id",
        "instances",
        ["tenant_id", "agent_id"],
    )

    # audit_logs: time-ordered feed per tenant.
    # sa.text("created_at DESC") produces a descending key so that
    # "ORDER BY created_at DESC LIMIT N" index-scans rather than seqscans.
    op.create_index(
        "ix_audit_logs_tenant_created_at",
        "audit_logs",
        ["tenant_id", sa.text("created_at DESC")],
    )

    # agents: active-agent listing per tenant
    op.create_index(
        "ix_agents_tenant_is_revoked",
        "agents",
        ["tenant_id", "is_revoked"],
    )


def downgrade() -> None:
    op.drop_index("ix_agents_tenant_is_revoked", table_name="agents")
    op.drop_index("ix_audit_logs_tenant_created_at", table_name="audit_logs")
    op.drop_index("ix_instances_tenant_agent_id", table_name="instances")
    op.drop_index("ix_instances_tenant_status", table_name="instances")
