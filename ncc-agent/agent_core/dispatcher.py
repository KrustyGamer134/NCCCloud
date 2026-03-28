"""
Command dispatcher.

Receives a parsed command message from the backend, routes it to the correct
AdminAPI method, and sends the result envelope back over the websocket.

Supported actions and their AdminAPI mappings
---------------------------------------------
start          → AdminAPI.start_instance(plugin_name, instance_id)
stop           → AdminAPI.stop_instance(plugin_name, instance_id)
restart        → AdminAPI.restart_instance(plugin_name, instance_id)
install_deps   → AdminAPI.install_deps(plugin_name, instance_id)
install_server → AdminAPI.install_server(plugin_name, instance_id)
get_status     → AdminAPI.read_cached_instance_status(plugin_name, instance_id)
get_install_progress → AdminAPI.get_install_progress(plugin_name, instance_id, last_lines)
fetch_logs     → AdminAPI.get_log_tail(plugin_name, instance_id, log_name, last_lines)
               NOTE: AdminAPI.get_log_tail requires a log_name parameter.
               The payload may supply {"log_name": "...", "lines": N}.
               When log_name is absent "ShooterGame" is used as a sensible default
               for ARK-family servers.
"""

import asyncio
import json
import logging

logger = logging.getLogger(__name__)

_DEFAULT_LOG_NAME = "ShooterGame"
_DEFAULT_LOG_LINES = 100

# Keys that belong to the message envelope, not to the action-specific payload.
# Everything else in a message is data the relay spread there via **payload.
_ENVELOPE_KEYS = frozenset(
    {"type", "action", "command_id", "plugin_name", "instance_id", "plugin_json", "payload"}
)


def _build_result(command_id: str, status: str, data) -> dict:
    return {
        "type": "command_result",
        "command_id": command_id,
        "status": status,
        "data": data,
    }


async def dispatch_command(msg: dict, admin_api, websocket) -> None:
    """
    Parse *msg*, call the appropriate AdminAPI method, and send the result
    envelope back over *websocket*.
    """
    command_id = msg.get("command_id", "")
    action = msg.get("action", "")
    plugin_name = msg.get("plugin_name", "")
    instance_id = msg.get("instance_id", "")
    plugin_json: dict = msg.get("plugin_json") or {}
    # The relay spreads the caller's payload dict as top-level message fields
    # (agent_relay.py: command_dict = {"type": ..., "action": ..., **payload}).
    # Re-assemble an action-specific payload dict from those top-level fields so
    # _route handlers work correctly.  An explicit nested "payload" key takes
    # precedence over top-level fields for forward-compatibility.
    payload: dict = {
        **{k: v for k, v in msg.items() if k not in _ENVELOPE_KEYS},
        **(msg.get("payload") or {}),
    }

    logger.info(
        "Dispatching command command_id=%s action=%s plugin=%s instance=%s",
        command_id,
        action,
        plugin_name,
        instance_id,
    )

    # Ensure the plugin is registered before routing.  If the agent started
    # without local plugin files (or the plugin directory was empty) this
    # registers the plugin on-the-fly from the catalog JSON sent by the backend.
    if plugin_name and plugin_json and hasattr(admin_api, "ensure_plugin_registered"):
        try:
            admin_api.ensure_plugin_registered(plugin_name, plugin_json)
        except Exception as reg_exc:
            logger.warning(
                "Could not pre-register plugin %r from catalog JSON: %s",
                plugin_name,
                reg_exc,
            )

    try:
        if action == "install_server":
            # SteamCMD installs are long-running and must not block the async
            # websocket loop, or the backend marks the agent offline.
            result_data = await asyncio.to_thread(
                _route,
                action,
                plugin_name,
                instance_id,
                payload,
                admin_api,
            )
        else:
            result_data = _route(action, plugin_name, instance_id, payload, admin_api)
        envelope = _build_result(command_id, "success", result_data)
    except Exception as exc:
        logger.exception(
            "Error dispatching command command_id=%s action=%s: %s",
            command_id,
            action,
            exc,
        )
        envelope = _build_result(command_id, "error", {"message": str(exc)})

    try:
        await websocket.send(json.dumps(envelope))
    except Exception as send_exc:
        logger.error(
            "Failed to send command result for command_id=%s: %s",
            command_id,
            send_exc,
        )


def _route(action: str, plugin_name: str, instance_id: str, payload: dict, admin_api):
    """Synchronous routing layer — returns the raw AdminAPI response."""

    if action == "start":
        logger.info("start_instance: plugin=%r instance=%r", plugin_name, instance_id)
        try:
            result = admin_api.start_instance(plugin_name, instance_id)
            logger.info("start_instance returned: %r", result)
            return result
        except Exception as exc:
            logger.exception(
                "start_instance raised: plugin=%r instance=%r error=%s",
                plugin_name, instance_id, exc,
            )
            raise

    if action == "stop":
        logger.info("stop_instance: plugin=%r instance=%r", plugin_name, instance_id)
        try:
            result = admin_api.stop_instance(plugin_name, instance_id)
            logger.info("stop_instance returned: %r", result)
            return result
        except Exception as exc:
            logger.exception(
                "stop_instance raised: plugin=%r instance=%r error=%s",
                plugin_name, instance_id, exc,
            )
            raise

    if action == "restart":
        logger.info("restart_instance: plugin=%r instance=%r", plugin_name, instance_id)
        try:
            result = admin_api.restart_instance(plugin_name, instance_id)
            logger.info("restart_instance returned: %r", result)
            return result
        except Exception as exc:
            logger.exception(
                "restart_instance raised: plugin=%r instance=%r error=%s",
                plugin_name, instance_id, exc,
            )
            raise

    if action == "add_instance":
        return admin_api.add_instance(plugin_name, instance_id)

    if action == "allocate_instance_ports":
        return admin_api.allocate_instance_ports(plugin_name)

    if action == "configure_instance":
        return admin_api.configure_instance(
            plugin_name,
            instance_id,
            payload.get("map_name") or payload.get("map") or "",
            int(payload.get("game_port") or 0),
            int(payload.get("rcon_port") or 0),
            mods=payload.get("mods") or [],
            passive_mods=payload.get("passive_mods") or [],
            map_mod=payload.get("map_mod"),
        )

    if action == "set_instance_plugin_config_fields":
        return admin_api.set_instance_plugin_config_fields(
            plugin_name,
            instance_id,
            payload.get("fields") or {},
        )

    if action == "set_cluster_config_fields":
        return admin_api.set_cluster_config_fields(payload.get("fields") or {})

    if action == "install_deps":
        return admin_api.install_deps(plugin_name, instance_id)

    if action == "install_server":
        return admin_api.install_server(plugin_name, instance_id)

    if action == "get_status":
        # Returns a plain dict (not the standard envelope), consistent with how
        # read_cached_instance_status is used throughout the codebase.
        return admin_api.read_cached_instance_status(plugin_name, instance_id)

    if action == "get_install_progress":
        lines = int(payload.get("lines") or 50)
        return admin_api.get_install_progress(plugin_name, instance_id, last_lines=lines)

    if action == "fetch_logs":
        log_name = payload.get("log_name") or _DEFAULT_LOG_NAME
        lines = int(payload.get("lines") or _DEFAULT_LOG_LINES)
        # AdminAPI.get_log_tail(plugin_name, instance_id, log_name, last_lines=200)
        return admin_api.get_log_tail(plugin_name, instance_id, log_name, last_lines=lines)

    if action == "discover":
        import os

        gameservers_root = payload.get("gameservers_root") or ""

        # Fall back to the orchestrator's cluster_root when the payload is empty.
        if not gameservers_root:
            orch = getattr(admin_api, "_orchestrator", None)
            gameservers_root = str(getattr(orch, "cluster_root", "") or "")

        servers = []
        if gameservers_root and os.path.isdir(gameservers_root):
            try:
                for entry in sorted(os.scandir(gameservers_root), key=lambda e: e.name.lower()):
                    if entry.is_dir():
                        servers.append({"name": entry.name, "path": entry.path})
            except OSError as exc:
                logger.error("discover: error scanning %r: %s", gameservers_root, exc)
                return {"servers": [], "gameservers_root": gameservers_root, "error": str(exc)}
        else:
            logger.warning(
                "discover: gameservers_root %r is empty or not a directory", gameservers_root
            )

        logger.info(
            "discover: found %d server folder(s) under %r", len(servers), gameservers_root
        )
        return {"servers": servers, "gameservers_root": gameservers_root}

    logger.warning("Unknown action received: %r (command will return error)", action)
    return _build_result("", "error", {"message": f"Unknown action: {action}"})
