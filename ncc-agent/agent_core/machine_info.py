"""
Machine-level metadata helpers.

These functions are designed to be called once per connection attempt. They
are best-effort: they never raise, and return None when information cannot
be obtained (e.g. no internet access, STUN server down).
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_IPIFY_URL = "https://api.ipify.org?format=json"
_TIMEOUT = 5.0  # seconds


async def get_public_ip() -> str | None:
    """
    Return the agent machine's public IPv4 address by querying ipify.org.

    Returns:
        IP address string (e.g. "203.0.113.42"), or None if the request
        fails for any reason (network error, timeout, unexpected response).
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(_IPIFY_URL)
            response.raise_for_status()
            data = response.json()
            ip: str = data["ip"]
            logger.debug("Public IP detected: %s", ip)
            return ip
    except httpx.TimeoutException:
        logger.debug("get_public_ip timed out after %.0fs", _TIMEOUT)
        return None
    except Exception as exc:
        logger.debug("get_public_ip failed: %s", exc)
        return None
