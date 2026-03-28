from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import bcrypt
from fastapi import WebSocket, WebSocketDisconnect
from packaging.version import InvalidVersion, Version
from sqlalchemy import select, update

from db.models import Agent, Instance
from db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Version policy
# ---------------------------------------------------------------------------
# Agents below MIN_SUPPORTED_AGENT are rejected outright.
# Agents at or above MIN_SUPPORTED_AGENT but below CURRENT_AGENT_VERSION
# are warned to upgrade but allowed to connect.
# Agents at or above CURRENT_AGENT_VERSION receive status="ok".
MIN_SUPPORTED_AGENT: str = "0.1.0"
CURRENT_AGENT_VERSION: str = "0.1.0"


def _check_agent_version(agent_version: str | None) -> tuple[str, str]:
    """
    Return (ack_status, message) based on the reported agent version.

    ack_status is one of: "ok" | "warn" | "rejected"
    message is empty for "ok", informational for "warn"/"rejected".
    """
    if not agent_version:
        return "warn", "Agent did not report a version; upgrade recommended"

    try:
        agent_ver = Version(agent_version)
        min_ver = Version(MIN_SUPPORTED_AGENT)
        current_ver = Version(CURRENT_AGENT_VERSION)
    except InvalidVersion:
        return "rejected", f"Invalid agent version string: {agent_version!r}"

    if agent_ver < min_ver:
        return (
            "rejected",
            f"Agent version {agent_version} is below the minimum supported "
            f"version {MIN_SUPPORTED_AGENT}. Please upgrade.",
        )

    if agent_ver < current_ver:
        return (
            "warn",
            f"Agent version {agent_version} is outdated. "
            f"Please upgrade to {CURRENT_AGENT_VERSION}.",
        )

    return "ok", ""


# agent_id (str) -> WebSocket
_agent_connections: dict[str, WebSocket] = {}

# command_id (str) -> asyncio.Future
_pending_commands: dict[str, asyncio.Future] = {}

_COMMAND_TIMEOUT = 30  # seconds
_INSTALL_SERVER_TIMEOUT = 60 * 60 * 3  # 3 hours


def _command_timeout_for(command_dict: dict[str, Any]) -> float:
    action = str((command_dict or {}).get("action") or "").strip().lower()
    if action == "install_server":
        return float(_INSTALL_SERVER_TIMEOUT)
    return float(_COMMAND_TIMEOUT)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
async def _authenticate_agent(
    agent_id: str, api_key: str
) -> Agent | None:
    """Verify agent credentials. Returns the Agent ORM object or None."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Agent).where(Agent.agent_id == uuid.UUID(agent_id))
        )
        agent = result.scalar_one_or_none()

    if agent is None:
        return None
    if agent.is_revoked:
        return None

    try:
        valid = bcrypt.checkpw(api_key.encode(), agent.api_key_hash.encode())
    except Exception as exc:
        logger.error("bcrypt check failed for agent %s: %s", agent_id, exc)
        return None

    return agent if valid else None


async def _update_agent_last_seen(agent_id: str) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Agent).where(Agent.agent_id == uuid.UUID(agent_id))
        )
        agent = result.scalar_one_or_none()
        if agent:
            agent.last_seen = datetime.now(tz=timezone.utc)
            db.add(agent)
            await db.commit()


async def _handle_status_update(agent: Agent, data: dict[str, Any]) -> None:
    """
    Persist a status_update snapshot from the agent (CORE-003 v1.2).

    Two-phase write
    ---------------
    Phase 1 — Blanket heartbeat:
        UPDATE instances SET agent_last_seen = now()
        WHERE tenant_id = <agent.tenant_id> AND agent_id = <agent.agent_id>

        This guarantees that *every* instance belonging to the agent reflects
        the latest contact time, even for instances not present in the snapshot.

    Phase 2 — Per-instance status:
        For each instance entry in the snapshot, SELECT the row and update
        status / install_status if the snapshot carries those fields.

    After both phases commit, the updated rows are broadcast to connected
    web clients.

    Expected data format (from the agent status_reporter):
    {
        "instances": [
            {"instance_id": "...", "status": "...", "install_status": "..."},
            ...
        ]
    }
    Fallback: flat dict keyed by instance_id / plugin_id (legacy snapshots).
    """
    from api.websocket import broadcast_to_tenant

    tenant_id = str(agent.tenant_id)
    now = datetime.now(tz=timezone.utc)

    # Normalise snapshot into a flat list of instance dicts.
    instances_data: list[dict] = data.get("instances", [])
    if not instances_data and isinstance(data, dict):
        # Fallback: top-level keys are instance_ids / plugin_ids.
        for k, v in data.items():
            if k != "instances" and isinstance(v, dict):
                instances_data.append({"instance_id": k, **v})

    updated_instances: list[dict] = []

    async with AsyncSessionLocal() as db:
        # ── Phase 1: stamp agent_last_seen on every instance for this agent ──
        await db.execute(
            update(Instance)
            .where(
                Instance.tenant_id == agent.tenant_id,
                Instance.agent_id == agent.agent_id,
            )
            .values(agent_last_seen=now)
        )

        # ── Phase 2: upsert status / install_status from the snapshot ─────────
        for item in instances_data:
            instance_id = item.get("instance_id")
            plugin_id = item.get("plugin_id")

            stmt = select(Instance).where(
                Instance.tenant_id == agent.tenant_id,
                Instance.agent_id == agent.agent_id,
            )
            if instance_id:
                try:
                    stmt = stmt.where(Instance.instance_id == uuid.UUID(instance_id))
                except (ValueError, AttributeError):
                    pass
            elif plugin_id:
                stmt = stmt.where(Instance.plugin_id == plugin_id)
            else:
                continue

            result = await db.execute(stmt)
            inst = result.scalar_one_or_none()

            if inst is None:
                continue

            if "status" in item:
                inst.status = item["status"]
            if "install_status" in item:
                inst.install_status = item["install_status"]
            db.add(inst)
            updated_instances.append(
                {
                    "instance_id": str(inst.instance_id),
                    "status": inst.status,
                    "install_status": inst.install_status,
                    "agent_last_seen": now.isoformat(),
                }
            )

        await db.commit()

    if updated_instances:
        await broadcast_to_tenant(
            tenant_id,
            {
                "type": "status_update",
                "agent_id": str(agent.agent_id),
                "instances": updated_instances,
            },
        )


# ---------------------------------------------------------------------------
# WebSocket handler
# ---------------------------------------------------------------------------
async def agent_ws_endpoint(websocket: WebSocket) -> None:
    """WebSocket handler for /agent/ws."""
    await websocket.accept()

    # Step 1: Wait for hello message
    try:
        hello = await asyncio.wait_for(websocket.receive_json(), timeout=15)
    except asyncio.TimeoutError:
        logger.warning("Agent did not send hello in time; closing")
        await websocket.close(code=4008, reason="Hello timeout")
        return
    except WebSocketDisconnect:
        return
    except Exception as exc:
        logger.error("Error receiving hello: %s", exc)
        await websocket.close(code=4000, reason="Protocol error")
        return

    if hello.get("type") != "hello":
        await websocket.send_json({"type": "hello_ack", "status": "rejected", "reason": "Expected hello"})
        await websocket.close(code=4000, reason="Protocol error")
        return

    agent_id: str = hello.get("agent_id", "")
    api_key: str = hello.get("api_key", "")
    agent_version: str | None = hello.get("agent_version")
    public_ip: str | None = hello.get("public_ip") or None

    agent = await _authenticate_agent(agent_id, api_key)

    if agent is None:
        await websocket.send_json({"type": "hello_ack", "status": "rejected", "reason": "Invalid credentials"})
        await websocket.close(code=4001, reason="Unauthorized")
        return

    # Version compatibility check — runs before we accept the connection.
    ack_status, ack_message = _check_agent_version(agent_version)
    if ack_status == "rejected":
        await websocket.send_json({
            "type": "hello_ack",
            "status": "rejected",
            "reason": ack_message,
        })
        await websocket.close(code=4003, reason="Agent version rejected")
        logger.warning(
            "Rejected agent %s: version=%s reason=%s",
            agent_id, agent_version, ack_message,
        )
        return

    # Persist last_seen, agent_version, and public_ip (if changed).
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Agent).where(Agent.agent_id == agent.agent_id)
        )
        db_agent = result.scalar_one_or_none()
        if db_agent:
            db_agent.last_seen = datetime.now(tz=timezone.utc)
            if agent_version:
                db_agent.agent_version = agent_version
            if public_ip is not None and public_ip != db_agent.public_ip:
                db_agent.public_ip = public_ip
            db.add(db_agent)
            await db.commit()
            agent = db_agent

    # Build and send hello_ack with the version-derived status.
    ack: dict = {"type": "hello_ack", "status": ack_status}
    if ack_message:
        ack["message"] = ack_message
    await websocket.send_json(ack)

    _agent_connections[agent_id] = websocket
    logger.info(
        "Agent connected: agent_id=%s version=%s public_ip=%s ack_status=%s",
        agent_id, agent_version, public_ip, ack_status,
    )

    # Step 2: Message loop
    try:
        while True:
            try:
                message = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except Exception as exc:
                logger.error("Error receiving message from agent %s: %s", agent_id, exc)
                break

            msg_type = message.get("type")

            if msg_type == "heartbeat":
                await _update_agent_last_seen(agent_id)

            elif msg_type == "status_update":
                status_data = message.get("data", {})
                try:
                    await _handle_status_update(agent, status_data)
                except Exception as exc:
                    logger.error("Error handling status_update from agent %s: %s", agent_id, exc)

            elif msg_type == "command_result":
                command_id: str = message.get("command_id", "")
                future = _pending_commands.get(command_id)
                if future and not future.done():
                    result_payload = {
                        "status": message.get("status", "unknown"),
                        "data": message.get("data", {}),
                    }
                    future.set_result(result_payload)
                else:
                    logger.debug(
                        "Received command_result for unknown/expired command_id=%s",
                        command_id,
                    )

            else:
                logger.debug("Unknown message type from agent %s: %s", agent_id, msg_type)

    except Exception as exc:
        logger.error("Unexpected error in agent WS loop for agent %s: %s", agent_id, exc)
    finally:
        _agent_connections.pop(agent_id, None)
        logger.info("Agent disconnected: agent_id=%s", agent_id)


# ---------------------------------------------------------------------------
# Send command to agent
# ---------------------------------------------------------------------------
async def send_command_to_agent(agent_id: str, command_dict: dict) -> dict:
    """
    Send a command to a connected agent and wait for the result.

    Raises HTTPException 504 on timeout, 503 if agent not connected.
    """
    from fastapi import HTTPException

    ws = _agent_connections.get(agent_id)
    if ws is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "Agent not connected", "code": "AGENT_OFFLINE"},
        )

    command_id = str(uuid.uuid4())
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    _pending_commands[command_id] = future
    timeout_seconds = _command_timeout_for(command_dict)

    try:
        payload = {**command_dict, "command_id": command_id}
        await ws.send_json(payload)

        result = await asyncio.wait_for(future, timeout=timeout_seconds)
        return result
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail={"error": "Agent command timed out", "code": "AGENT_TIMEOUT"},
        )
    except Exception as exc:
        logger.error("Error sending command to agent %s: %s", agent_id, exc)
        raise HTTPException(
            status_code=500,
            detail={"error": "Failed to send command to agent", "code": "AGENT_ERROR"},
        )
    finally:
        _pending_commands.pop(command_id, None)
