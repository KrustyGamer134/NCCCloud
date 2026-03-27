"""
Generic process monitoring for Steam game server plugins.

All game-specific values (log paths, ready signals, version regexes,
process name lists) are passed in as parameters.
"""
from __future__ import annotations

import os
from typing import List, Optional


def _runtime_process_state(
    *,
    paths: dict,
    get_proc_fn,
    proc_is_running_fn,
    read_pid_file_fn,
    tasklist_pid_running_fn,
    tasklist_first_ark_pid_fn,
) -> dict:
    warnings: List[str] = []
    pid: Optional[int] = None
    pid_file_present = bool(os.path.exists(paths["pid_file"]) and os.path.isfile(paths["pid_file"]))
    pid_from_file: Optional[int] = None
    process_probe_running = False

    proc = get_proc_fn(paths["instance_id"])
    if proc is not None and proc_is_running_fn(proc):
        process_probe_running = True
        pid = getattr(proc, "pid", None)
    else:
        pid_from_file = read_pid_file_fn(paths["pid_file"])
        if pid_from_file is not None:
            pid_ok, warn = tasklist_pid_running_fn(int(pid_from_file))
            if warn:
                warnings.append(str(warn))
            if pid_ok:
                process_probe_running = True
                pid = int(pid_from_file)

    return {
        "warnings": warnings,
        "pid": pid,
        "pid_file_present": pid_file_present,
        "pid_from_file": pid_from_file,
        "process_probe_running": process_probe_running,
    }


def _runtime_log_state(
    *,
    paths: dict,
    tail_file_lines_fn,
    ready_signal: str,
    status_log_tail_lines: int,
    version_log_tail_lines: int,
    extract_version_token_fn,
    extract_running_version_fn,
    include_missing_log_warnings: bool,
) -> dict:
    warnings: List[str] = []

    server_log_found = False
    server_tail = []
    ready_line_found = False
    ready_line_value = None
    if tail_file_lines_fn is not None and status_log_tail_lines > 0:
        server_log_found, server_tail = tail_file_lines_fn(paths["server_log"], status_log_tail_lines)
        if server_log_found:
            for line in reversed(server_tail):
                if ready_signal and ready_signal in str(line):
                    ready_line_found = True
                    ready_line_value = str(line)
                    break
        elif include_missing_log_warnings:
            warnings.append(f"server log not found: {paths['server_log']}")

    install_log_found = False
    install_tail = []
    if tail_file_lines_fn is not None and version_log_tail_lines > 0:
        install_log_found, install_tail = tail_file_lines_fn(paths["install_server_log"], version_log_tail_lines)
        if not install_log_found and include_missing_log_warnings:
            warnings.append(f"install server log not found: {paths['install_server_log']}")

    installed_version = None
    running_version = None
    if callable(extract_version_token_fn):
        installed_version = extract_version_token_fn(install_tail if install_log_found else [])
    if callable(extract_running_version_fn):
        running_version = extract_running_version_fn(server_tail if server_log_found else [])

    return {
        "warnings": warnings,
        "server_log_found": server_log_found,
        "server_tail": server_tail,
        "ready_line_found": ready_line_found,
        "ready_line_value": ready_line_value,
        "installed_version": installed_version,
        "running_version": running_version,
    }


def _runtime_snapshot(
    instance_id: str,
    *,
    resolve_effective_layout_fn,
    resolve_effective_server_name_fn,
    resolve_runtime_paths_fn,
    get_proc_fn,
    proc_is_running_fn,
    read_pid_file_fn,
    tasklist_pid_running_fn,
    tasklist_first_ark_pid_fn,
    tail_file_lines_fn=None,
    extract_version_token_fn=None,
    extract_running_version_fn=None,
    ready_signal: str = "",
    status_log_tail_lines: int = 0,
    version_log_tail_lines: int = 0,
    include_missing_log_warnings: bool = False,
) -> dict:
    defaults, inst, layout = resolve_effective_layout_fn(instance_id)
    paths = resolve_runtime_paths_fn(layout, instance_id)
    process_state = _runtime_process_state(
        paths={"pid_file": paths["pid_file"], "instance_id": str(instance_id)},
        get_proc_fn=get_proc_fn,
        proc_is_running_fn=proc_is_running_fn,
        read_pid_file_fn=read_pid_file_fn,
        tasklist_pid_running_fn=tasklist_pid_running_fn,
        tasklist_first_ark_pid_fn=tasklist_first_ark_pid_fn,
    )
    log_state = _runtime_log_state(
        paths=paths,
        tail_file_lines_fn=tail_file_lines_fn,
        ready_signal=ready_signal,
        status_log_tail_lines=status_log_tail_lines,
        version_log_tail_lines=version_log_tail_lines,
        extract_version_token_fn=extract_version_token_fn,
        extract_running_version_fn=extract_running_version_fn,
        include_missing_log_warnings=include_missing_log_warnings,
    )
    warnings = list(process_state["warnings"]) + list(log_state["warnings"])
    return {
        "display_name": str(resolve_effective_server_name_fn(defaults, inst) or "").strip(),
        "paths": paths,
        "process_state": process_state,
        "log_state": log_state,
        "warnings": warnings,
    }


def _runtime_base_payload(snapshot: dict) -> dict:
    process_state = snapshot["process_state"]
    log_state = snapshot["log_state"]
    running = bool(process_state["process_probe_running"])
    return {
        "ok": True,
        "display_name": str(snapshot["display_name"] or "").strip(),
        "running": running,
        "ready": bool(log_state["ready_line_found"]),
        "pid": int(process_state["pid"]) if process_state["pid"] is not None and running else None,
        "pid_file_present": bool(process_state["pid_file_present"]),
        "pid_from_file": int(process_state["pid_from_file"]) if process_state["pid_from_file"] is not None else None,
        "process_probe_running": bool(process_state["process_probe_running"]),
        "version": {
            "installed": log_state["installed_version"],
            "running": log_state["running_version"],
        },
        "warnings": list(snapshot["warnings"]),
        "errors": [],
    }


def runtime_summary_payload(
    instance_id: str,
    *,
    resolve_effective_layout_fn,
    resolve_effective_server_name_fn,
    resolve_runtime_paths_fn,
    get_proc_fn,
    proc_is_running_fn,
    read_pid_file_fn,
    tasklist_pid_running_fn,
    tasklist_first_ark_pid_fn,
    tail_file_lines_fn=None,
    extract_version_token_fn=None,
    extract_running_version_fn=None,
    ready_signal: str = "",
    status_log_tail_lines: int = 0,
    version_log_tail_lines: int = 0,
) -> dict:
    snapshot = _runtime_snapshot(
        instance_id,
        resolve_effective_layout_fn=resolve_effective_layout_fn,
        resolve_effective_server_name_fn=resolve_effective_server_name_fn,
        resolve_runtime_paths_fn=resolve_runtime_paths_fn,
        get_proc_fn=get_proc_fn,
        proc_is_running_fn=proc_is_running_fn,
        read_pid_file_fn=read_pid_file_fn,
        tasklist_pid_running_fn=tasklist_pid_running_fn,
        tasklist_first_ark_pid_fn=tasklist_first_ark_pid_fn,
        tail_file_lines_fn=tail_file_lines_fn,
        extract_version_token_fn=extract_version_token_fn,
        extract_running_version_fn=extract_running_version_fn,
        ready_signal=ready_signal,
        status_log_tail_lines=status_log_tail_lines,
        version_log_tail_lines=version_log_tail_lines,
        include_missing_log_warnings=False,
    )
    return _runtime_base_payload(snapshot)


def runtime_status_payload(
    instance_id: str,
    *,
    resolve_effective_layout_fn,
    resolve_effective_server_name_fn,
    resolve_runtime_paths_fn,
    get_proc_fn,
    proc_is_running_fn,
    read_pid_file_fn,
    tasklist_pid_running_fn,
    tasklist_first_ark_pid_fn,
    tail_file_lines_fn,
    extract_version_token_fn,
    extract_running_version_fn,
    ready_signal: str,
    status_log_tail_lines: int,
    version_log_tail_lines: int,
) -> dict:
    snapshot = _runtime_snapshot(
        instance_id,
        resolve_effective_layout_fn=resolve_effective_layout_fn,
        resolve_effective_server_name_fn=resolve_effective_server_name_fn,
        resolve_runtime_paths_fn=resolve_runtime_paths_fn,
        get_proc_fn=get_proc_fn,
        proc_is_running_fn=proc_is_running_fn,
        read_pid_file_fn=read_pid_file_fn,
        tasklist_pid_running_fn=tasklist_pid_running_fn,
        tasklist_first_ark_pid_fn=tasklist_first_ark_pid_fn,
        tail_file_lines_fn=tail_file_lines_fn,
        extract_version_token_fn=extract_version_token_fn,
        extract_running_version_fn=extract_running_version_fn,
        ready_signal=ready_signal,
        status_log_tail_lines=status_log_tail_lines,
        version_log_tail_lines=version_log_tail_lines,
        include_missing_log_warnings=True,
    )
    payload = _runtime_base_payload(snapshot)
    payload["paths"] = snapshot["paths"]
    payload["signals"] = {
        "ready_log_line_found": bool(snapshot["log_state"]["ready_line_found"]),
        "ready_log_line": snapshot["log_state"]["ready_line_value"],
    }
    return payload
