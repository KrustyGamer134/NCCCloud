from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Tenant, User
from db.session import get_db

router = APIRouter(tags=["auth"])


class ProvisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: str
    user_id: str
    role: str
    is_new: bool


@router.post("/provision", response_model=ProvisionResponse)
async def provision(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ProvisionResponse:
    """
    Provision a user after first successful JWT validation.
    The middleware has already validated the JWT token and attached user_id
    to request.state, but the user may not yet exist in the DB (that's fine,
    /auth/provision is skipped by the auth middleware).

    We re-derive user_id from the Authorization header ourselves when the
    middleware skips this route, so we read the claim directly.
    """
    # The middleware skips /auth/provision, so we get user_id from the
    # JWT claim that was decoded independently. We read request.state if set
    # (in case middleware ran), otherwise extract from token inline.
    user_id: str | None = getattr(request.state, "user_id", None)

    if user_id is None:
        # Decode the token ourselves since middleware skipped this route
        from core.auth import _get_jwks
        from core.settings import settings
        from jose import jwt as jose_jwt

        auth_header = request.headers.get("Authorization", "")
        token = auth_header[len("Bearer "):] if auth_header.startswith("Bearer ") else ""
        jwks = await _get_jwks()
        payload = jose_jwt.decode(
            token,
            jwks,
            algorithms=[settings.jwt_algorithm],
            options={"verify_aud": False},
        )
        user_id = payload.get("sub", "")
        email_from_token: str = payload.get("email", "")
    else:
        # Middleware ran — get email from token claims
        auth_header = request.headers.get("Authorization", "")
        token = auth_header[len("Bearer "):] if auth_header.startswith("Bearer ") else ""
        from core.auth import _get_jwks
        from core.settings import settings
        from jose import jwt as jose_jwt

        jwks = await _get_jwks()
        payload = jose_jwt.decode(
            token,
            jwks,
            algorithms=[settings.jwt_algorithm],
            options={"verify_aud": False},
        )
        email_from_token = payload.get("email", "")

    # Check if user already exists
    result = await db.execute(select(User).where(User.user_id == user_id))
    existing_user = result.scalar_one_or_none()

    if existing_user is not None:
        return ProvisionResponse(
            tenant_id=str(existing_user.tenant_id),
            user_id=existing_user.user_id,
            role=existing_user.role,
            is_new=False,
        )

    # New user — derive tenant name from email domain
    email = email_from_token or f"{user_id}@unknown"
    domain = email.split("@")[-1] if "@" in email else email

    tenant = Tenant(
        tenant_id=uuid.uuid4(),
        name=domain,
        plan="free",
    )
    db.add(tenant)
    await db.flush()  # get tenant_id assigned

    user = User(
        user_id=user_id,
        tenant_id=tenant.tenant_id,
        email=email,
        role="owner",
    )
    db.add(user)
    await db.flush()

    return ProvisionResponse(
        tenant_id=str(tenant.tenant_id),
        user_id=user.user_id,
        role=user.role,
        is_new=True,
    )
