from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from db.models import User
from db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# tenant_id -> set of connected WebSockets
_connections: dict[str, set[WebSocket]] = {}


async def _authenticate_ws(token: str) -> tuple[str, str] | None:
    """
    Validate JWT token from WebSocket query param.
    Returns (user_id, tenant_id) or None if invalid.
    """
    from core.auth import _get_jwks
    from core.settings import settings
    from jose import JWTError, jwt

    try:
        jwks = await _get_jwks()
        payload = jwt.decode(
            token,
            jwks,
            algorithms=[settings.jwt_algorithm],
            options={"verify_aud": False},
        )
    except JWTError as exc:
        logger.debug("WebSocket JWT validation failed: %s", exc)
        return None
    except Exception as exc:
        logger.error("Unexpected error during WebSocket JWT validation: %s", exc)
        return None

    user_id: str | None = payload.get("sub")
    if not user_id:
        return None

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()

    if user is None:
        return None

    return user_id, str(user.tenant_id)


async def ws_events_endpoint(websocket: WebSocket) -> None:
    """WebSocket handler for /ws/events."""
    token = websocket.query_params.get("token", "")

    auth = await _authenticate_ws(token)
    if auth is None:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    user_id, tenant_id = auth
    await websocket.accept()

    # Register connection
    if tenant_id not in _connections:
        _connections[tenant_id] = set()
    _connections[tenant_id].add(websocket)

    logger.info("WebSocket client connected: user=%s tenant=%s", user_id, tenant_id)

    try:
        await websocket.send_json({"type": "connected", "tenant_id": tenant_id})

        # Keep alive — listen for disconnect or client messages
        while True:
            try:
                data = await websocket.receive_text()
                logger.debug("WS message from user=%s: %s", user_id, data)
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("WebSocket error for user=%s: %s", user_id, exc)
    finally:
        _connections.get(tenant_id, set()).discard(websocket)
        if tenant_id in _connections and not _connections[tenant_id]:
            del _connections[tenant_id]
        logger.info("WebSocket client disconnected: user=%s tenant=%s", user_id, tenant_id)


async def broadcast_to_tenant(tenant_id: str, event: dict[str, Any]) -> None:
    """Broadcast an event to all WebSocket clients for a given tenant."""
    sockets = list(_connections.get(tenant_id, set()))
    if not sockets:
        return

    disconnected: set[WebSocket] = set()
    for ws in sockets:
        try:
            await ws.send_json(event)
        except Exception as exc:
            logger.debug("Failed to send to websocket: %s", exc)
            disconnected.add(ws)

    if disconnected:
        remaining = _connections.get(tenant_id, set()) - disconnected
        if remaining:
            _connections[tenant_id] = remaining
        elif tenant_id in _connections:
            del _connections[tenant_id]
