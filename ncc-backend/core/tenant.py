from __future__ import annotations

from fastapi import HTTPException, Request


def require_tenant(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=403,
            detail={"error": "Forbidden", "code": "NO_TENANT"},
        )
    return tenant_id
