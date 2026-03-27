"""
Generic RCON orchestration for Steam game server plugins.

Game-specific values (stop sequences, client class, log functions)
are passed in as parameters.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple, cast

from core.rcon_client import GenericRconClient


def rcon_command_name(command: str) -> str:
    token = str(command or "").strip()
    if not token:
        return ""
    return token.split()[0]


def resolve_rcon_target(instance_id: str, *, load_plugin_defaults_fn, load_instance_config_fn) -> Tuple[str, Optional[int]]:
    defaults = load_plugin_defaults_fn()
    inst = load_instance_config_fn(instance_id)
    host = str(defaults.get("rcon_host") or "127.0.0.1")
    rcon_port = inst.get("rcon_port")
    if rcon_port is None:
        return host, None
    try:
        return host, int(rcon_port)
    except Exception:
        return host, None


def build_rcon_client(
    instance_id: str,
    *,
    load_plugin_defaults_fn,
    load_instance_config_fn,
    resolve_rcon_target_fn,
    test_mode_enabled_fn,
    client_cls=GenericRconClient,
):
    defaults = load_plugin_defaults_fn()
    inst = load_instance_config_fn(instance_id)
    host, rcon_port = resolve_rcon_target_fn(instance_id)
    password = str((inst.get("admin_password") or defaults.get("admin_password") or "")).strip()
    rcon_enabled = inst.get("rcon_enabled")
    if rcon_enabled is None:
        rcon_enabled = defaults.get("rcon_enabled")
    wire_log = test_mode_enabled_fn(defaults, inst)

    if not bool(rcon_enabled):
        return None, "RCON not configured: disabled"
    if rcon_port is None:
        return None, "RCON not configured: missing rcon_port in instance config"
    if not password:
        return None, "RCON not configured: missing admin_password"

    return (
        client_cls(
            host=host,
            port=int(rcon_port),
            password=password,
            instance_id=str(instance_id),
            wire_log=wire_log,
        ),
        None,
    )


def perform_graceful_stop(
    instance_id: str,
    layout: Dict[str, Optional[str]],
    *,
    stop_sequence: List[str],
    pid_file_path_fn,
    get_proc_fn,
    load_plugin_defaults_fn,
    resolve_rcon_target_fn,
    build_rcon_client_fn,
    source_rcon_client_cls,
    proc_is_running_fn,
    wait_or_kill_fn,
    clear_proc_fn,
    remove_pid_file_fn,
    log_rcon_send_fn,
    defaults: Optional[dict] = None,
    inst: Optional[dict] = None,
    proc=None,
    fallback_pid_fn=None,
) -> dict:
    pid_file = pid_file_path_fn(layout, instance_id)
    proc = proc if proc is not None else get_proc_fn(instance_id)

    rcon_attempted = False
    rcon_ok = False
    rcon_error = None

    host, rcon_port = resolve_rcon_target_fn(instance_id)
    client, warn = build_rcon_client_fn(instance_id)
    if defaults is None:
        defaults = load_plugin_defaults_fn()
    if inst is None:
        inst = {}
    admin_password = str((inst.get("admin_password") or defaults.get("admin_password") or "").strip())
    rcon_enabled = inst.get("rcon_enabled")
    if rcon_enabled is None:
        rcon_enabled = defaults.get("rcon_enabled")
    can_use_source = source_rcon_client_cls is not None and rcon_port is not None and bool(admin_password) and bool(rcon_enabled)
    can_use_fallback = client is not None
    if can_use_source or can_use_fallback:
        rcon_attempted = True
        try:
            for command in stop_sequence:
                log_rcon_send_fn(instance_id, host, rcon_port, command)
                quoted = f'"{command}"'
                if can_use_source:
                    with source_rcon_client_cls(host, int(rcon_port), passwd=admin_password) as rcon_client:
                        rcon_client.run(quoted)
                elif can_use_fallback and hasattr(client, "exec") and callable(getattr(client, "exec")):
                    client.exec(quoted)
                else:
                    raise RuntimeError("RCON client unavailable: rcon.source.Client import failed")
            rcon_ok = True
        except Exception as e:
            rcon_ok = False
            rcon_error = str(e)

    stopped = True
    killed = False
    if proc is not None and proc_is_running_fn(proc):
        if not rcon_ok:
            proc.terminate()
        stopped, killed = wait_or_kill_fn(proc)
    elif proc is None and fallback_pid_fn is not None:
        _fallback_pid = fallback_pid_fn()
        if _fallback_pid is not None:
            try:
                import subprocess as _subprocess
                _subprocess.run(
                    ["taskkill", "/F", "/PID", str(_fallback_pid)],
                    timeout=10,
                    capture_output=True,
                )
                killed = True
            except Exception:
                pass

    if stopped:
        clear_proc_fn(instance_id)
        remove_pid_file_fn(pid_file)
    payload = {
        "ok": True,
        "details": "graceful_stop complete",
        "warnings": [],
        "errors": [],
        "pid": getattr(proc, "pid", None) if proc is not None else None,
        "simulated": False,
        "instance_id": instance_id,
        "sequence": stop_sequence,
        "stopped": stopped,
        "killed": killed,
        "rcon_attempted": rcon_attempted,
        "rcon_ok": rcon_ok,
    }
    if client is None:
        payload["simulated"] = True
        payload["details"] = warn
    if rcon_error:
        cast(List[str], payload["warnings"]).append(f"rcon_error: {rcon_error}")
    return payload
