from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx
from jose import JWTError, jwt
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from core.settings import settings
from db.models import User
from db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JWKS cache
# ---------------------------------------------------------------------------
_jwks_cache: dict[str, Any] = {}
_jwks_cache_ts: float = 0.0
_jwks_lock = asyncio.Lock()
_JWKS_TTL = 3600  # 1 hour


async def _get_jwks() -> dict:
    global _jwks_cache, _jwks_cache_ts
    now = time.monotonic()
    if _jwks_cache and (now - _jwks_cache_ts) < _JWKS_TTL:
        return _jwks_cache

    async with _jwks_lock:
        # Double-check after acquiring lock
        now = time.monotonic()
        if _jwks_cache and (now - _jwks_cache_ts) < _JWKS_TTL:
            return _jwks_cache

        async with httpx.AsyncClient() as client:
            resp = await client.get(settings.clerk_jwks_url, timeout=10)
            resp.raise_for_status()
            data = resp.json()

        _jwks_cache = data
        _jwks_cache_ts = time.monotonic()
        return _jwks_cache


# ---------------------------------------------------------------------------
# Routes that skip authentication
# ---------------------------------------------------------------------------
_SKIP_PATHS = {
    "/health",
    "/ready",
    "/docs",
    "/openapi.json",
    "/auth/provision",
    "/agents/register",
}


def _should_skip(path: str) -> bool:
    if path in _SKIP_PATHS:
        return True
    # Also skip Swagger UI assets
    if path.startswith("/docs") or path.startswith("/redoc"):
        return True
    return False


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
class JWTAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if _should_skip(request.url.path):
            return await call_next(request)

        # Bypass auth for CORS preflight
        if request.method == "OPTIONS":
            return await call_next(request)

        # rest of the auth code...

        # Extract token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                {"error": "Unauthorized", "code": "UNAUTHORIZED"},
                status_code=401,
            )

        token = auth_header[len("Bearer "):]

        try:
            jwks = await _get_jwks()
            payload = jwt.decode(
                token,
                jwks,
                algorithms=[settings.jwt_algorithm],
                options={"verify_aud": False},
            )
        except JWTError as exc:
            logger.debug("JWT validation failed: %s", exc)
            return JSONResponse(
                {"error": "Unauthorized", "code": "UNAUTHORIZED"},
                status_code=401,
            )
        except Exception as exc:
            logger.error("Unexpected error during JWT validation: %s", exc)
            return JSONResponse(
                {"error": "Unauthorized", "code": "UNAUTHORIZED"},
                status_code=401,
            )

        user_id: str | None = payload.get("sub")
        if not user_id:
            return JSONResponse(
                {"error": "Unauthorized", "code": "UNAUTHORIZED"},
                status_code=401,
            )

        # Look up user in DB to get tenant_id
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(User).where(User.user_id == user_id)
                )
                user = result.scalar_one_or_none()
        except Exception as exc:
            logger.error("DB lookup failed during auth: %s", exc)
            return JSONResponse(
                {"error": "Unauthorized", "code": "UNAUTHORIZED"},
                status_code=401,
            )

        if user is None:
            # User not provisioned yet — only /auth/provision is allowed without a user record
            return JSONResponse(
                {"error": "Forbidden", "code": "FORBIDDEN"},
                status_code=403,
            )

        request.state.user_id = user.user_id
        request.state.tenant_id = str(user.tenant_id)

        return await call_next(request)
