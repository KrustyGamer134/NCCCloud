"""
Periodic status reporter.

Runs as a long-lived coroutine alongside the WebSocket connection loop.
Every STATUS_INTERVAL seconds it asks the AdminAPI for a full dashboard
snapshot and pushes it to the backend over the current WebSocket connection.

The reporter never raises — all exceptions are caught and logged so that a
transient AdminAPI or network error cannot kill the agent process.
"""

import asyncio
import logging
from typing import Callable

logger = logging.getLogger(__name__)

STATUS_INTERVAL: int = 15  # seconds between status pushes


async def run_status_reporter(
    agent_id: str,
    admin_api,
    send_json_fn: Callable,
    is_connected_fn: Callable,
) -> None:
    """
    Continuously send status snapshots to the backend.

    Parameters
    ----------
    agent_id:
        The registered agent identifier, included in every status message.
    admin_api:
        Live AdminAPI instance used to query the local cluster state.
    send_json_fn:
        Async callable used to send frames over the current live WebSocket.
    is_connected_fn:
        Zero-argument callable that returns True when the agent currently has a
        live WebSocket connection.
    """
    logger.info("Status reporter started (interval=%ds)", STATUS_INTERVAL)

    while True:
        await asyncio.sleep(STATUS_INTERVAL)

        if not is_connected_fn():
            logger.debug("Status reporter: no active connection, skipping snapshot")
            continue

        try:
            snapshot = await asyncio.to_thread(_get_snapshot, admin_api)
        except Exception as exc:
            logger.warning("Status reporter: failed to collect snapshot: %s", exc)
            continue

        try:
            await send_json_fn(
                {
                    "type": "status_update",
                    "agent_id": agent_id,
                    "data": snapshot,
                }
            )
            logger.debug("Status reporter: snapshot sent")
        except Exception as exc:
            logger.warning("Status reporter: failed to send snapshot: %s", exc)


def _get_snapshot(admin_api) -> dict:
    """
    Collect a full dashboard snapshot from the AdminAPI and return it in the
    normalised format expected by the backend's _handle_status_update:

        {"instances": [{"instance_id": "...", "status": "...", "install_status": "..."}, ...]}

    AdminAPI.get_dashboard_status_snapshot() returns an envelope:
        {"status": "success", "data": {"plugins": {plugin_name: {"status": [...], ...}}}}

    We unwrap that envelope so the backend can apply status updates directly
    without needing to know about AdminAPI internals.
    """
    if hasattr(admin_api, "get_dashboard_status_snapshot"):
        raw = admin_api.get_dashboard_status_snapshot()
    else:
        logger.warning(
            "get_dashboard_status_snapshot not found on AdminAPI — using fallback"
        )
        raw = _build_snapshot_fallback(admin_api)

    return _normalize_snapshot(raw)


def _normalize_snapshot(raw: dict) -> dict:
    """
    Unwrap the AdminAPI envelope and flatten all per-instance status dicts into
    a single list under the key "instances".

    Input:  {"status": "success", "data": {"plugins": {name: {"status": [...]}}}}
    Output: {"instances": [{"instance_id": "...", "status": "...", ...}, ...]}
    """
    instances: list[dict] = []
    plugins_data = (raw.get("data") or {}).get("plugins") or {}
    for plugin_data in plugins_data.values():
        for item in (plugin_data.get("status") or []):
            if isinstance(item, dict):
                instances.append(item)
    return {"instances": instances}


def _build_snapshot_fallback(admin_api) -> dict:
    """Build a snapshot envelope using individual AdminAPI calls."""
    grouped: dict = {}
    try:
        plugins = admin_api.get_all_plugins()
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    for plugin in plugins:
        plugin = str(plugin)
        statuses = []
        instance_ids = []
        err = None

        try:
            resp = admin_api.list_instances(plugin)
            if isinstance(resp, dict) and resp.get("status") == "success":
                data = resp.get("data") or {}
                raw_instances = data.get("instances") or []
                for item in raw_instances:
                    if isinstance(item, str):
                        instance_ids.append(item)
                    elif isinstance(item, dict) and item.get("instance_id") is not None:
                        instance_ids.append(str(item["instance_id"]))
            else:
                err = str(resp.get("message", "list_instances failed")) if isinstance(resp, dict) else "list_instances failed"
        except Exception as exc:
            err = str(exc)

        for iid in instance_ids:
            try:
                statuses.append(admin_api.read_cached_instance_status(plugin, iid))
            except Exception as exc:
                statuses.append({"plugin_name": plugin, "instance_id": iid, "error": str(exc)})

        grouped[plugin] = {"instance_ids": instance_ids, "status": statuses, "error": err}

    return {"status": "success", "data": {"plugins": grouped}}
