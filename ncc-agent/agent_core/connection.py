"""
WebSocket connection manager.

AgentConnection owns the single persistent connection to the NCC backend.
It reconnects automatically with exponential backoff and exposes the current
live WebSocket via the ``ws`` property so the status reporter can push
updates without coupling to the connection internals.

Heartbeat strategy
------------------
Inside the message loop ``asyncio.wait_for(ws.recv(), timeout=HEARTBEAT_INTERVAL)``
is used as a combined receive/timer primitive.  When the timeout fires a
heartbeat ping is sent and the loop continues.  This avoids spawning extra
tasks while keeping the connection alive through NAT / load-balancer idle
timeouts.
"""

import asyncio
import json
import logging
import sys

import websockets

from agent_core.dispatcher import dispatch_command
from agent_core.machine_info import get_public_ip
from agent_core.version import AGENT_VERSION

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL: float = 10.0   # seconds between heartbeat pings
HELLO_ACK_TIMEOUT: float = 10.0    # seconds to wait for hello_ack after connect
BACKOFF_BASE: float = 5.0          # initial reconnect delay in seconds
BACKOFF_MAX: float = 60.0          # maximum reconnect delay in seconds


class AgentConnection:
    def __init__(self, settings, admin_api):
        self._settings = settings
        self._admin_api = admin_api
        self._ws = None
        # Public IP is fetched once when connect_loop() starts and reused on
        # every subsequent reconnect.  A fresh process restart re-fetches it.
        self._public_ip: str | None = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def ws(self):
        """Return the current live WebSocket, or None if disconnected."""
        return self._ws

    async def connect_loop(self) -> None:
        """
        Main reconnection loop.  Runs forever; only exits on fatal errors
        (e.g. the backend explicitly rejects the agent).
        """
        # Fetch public IP once at startup.  Reconnects reuse the cached value
        # so a transient ipify outage during reconnection doesn't flip the
        # recorded IP to None.
        self._public_ip = await get_public_ip()
        logger.debug("Public IP at startup: %s", self._public_ip)

        delay = BACKOFF_BASE

        while True:
            try:
                await self._attempt_connection()
                # Successful session — reset backoff
                delay = BACKOFF_BASE
            except SystemExit:
                raise
            except Exception as exc:
                self._ws = None
                logger.warning(
                    "Connection lost: %s — reconnecting in %.0fs", exc, delay
                )

            await asyncio.sleep(delay)
            delay = min(delay * 2, BACKOFF_MAX)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _attempt_connection(self) -> None:
        url = self._settings.backend_ws_url
        logger.info("Connecting to backend at %s", url)

        async with websockets.connect(url) as ws:
            # Step 1: send hello using the IP cached at startup.
            hello = {
                "type": "hello",
                "agent_id": self._settings.agent_id,
                "agent_version": AGENT_VERSION,
                "api_key": self._settings.api_key,
                "public_ip": self._public_ip,
            }
            await ws.send(json.dumps(hello))
            logger.debug("Sent hello message (public_ip=%s)", self._public_ip)

            # Step 2: wait for hello_ack
            try:
                raw_ack = await asyncio.wait_for(ws.recv(), timeout=HELLO_ACK_TIMEOUT)
            except asyncio.TimeoutError:
                raise ConnectionError(
                    f"Timed out waiting for hello_ack after {HELLO_ACK_TIMEOUT}s"
                )

            ack = _parse_message(raw_ack)
            if not ack:
                raise ConnectionError("Received non-JSON hello_ack")

            status = ack.get("status", "")

            if status == "rejected":
                reason = ack.get("reason", "no reason given")
                logger.error("Backend rejected agent: %s", reason)
                sys.exit(1)

            if status not in ("ok", "warn"):
                raise ConnectionError(
                    f"Unexpected hello_ack status: {status!r}"
                )

            if status == "warn":
                logger.warning("Backend issued hello_ack with warning: %s", ack.get("message", ""))
            else:
                logger.info("hello_ack received — agent session established")

            # Step 3: enter message loop
            self._ws = ws
            try:
                await self._message_loop(ws)
            finally:
                self._ws = None

    async def _message_loop(self, ws) -> None:
        """
        Receive messages from the backend.

        Uses ``asyncio.wait_for`` with HEARTBEAT_INTERVAL as a timeout.
        When the timeout fires it means no message arrived within the window,
        so a heartbeat ping is sent to keep the connection alive.
        """
        logger.info("Entering message loop")

        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=HEARTBEAT_INTERVAL)
            except asyncio.TimeoutError:
                # No message received — send heartbeat and continue
                await self._send_heartbeat(ws)
                continue

            msg = _parse_message(raw)
            if msg is None:
                logger.warning("Received non-JSON message, ignoring: %r", raw[:200])
                continue

            msg_type = msg.get("type", "")

            if msg_type == "command":
                await dispatch_command(msg, self._admin_api, ws)
            else:
                logger.debug("Ignoring unhandled message type: %r", msg_type)

    async def _send_heartbeat(self, ws) -> None:
        heartbeat = {"type": "heartbeat", "agent_id": self._settings.agent_id}
        try:
            await ws.send(json.dumps(heartbeat))
            logger.debug("Heartbeat sent")
        except Exception as exc:
            logger.warning("Failed to send heartbeat: %s", exc)
            raise  # propagate so connect_loop triggers a reconnect


def _parse_message(raw) -> dict | None:
    """Parse a raw WebSocket message as JSON.  Returns None on failure."""
    try:
        return json.loads(raw)
    except Exception:
        return None
