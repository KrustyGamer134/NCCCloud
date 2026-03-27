"""
Generic SteamCMD install and version-check helpers for Steam game server plugins.

All game-specific values (app IDs, server directories, log prefixes) are passed
in as parameters.
"""
from __future__ import annotations

import os
import time
from typing import List, Optional, Tuple

from core.steamcmd import run_command as _steamcmd_run_command


_STEAMCMD_INSTALL_FATAL_MARKERS = (
    "ERROR! Failed to install app",
    "Missing configuration",
    "No subscription",
    "Invalid platform",
)


def extract_steamcmd_target_version(text: str) -> Optional[str]:
    import re
    text_value = str(text or "")
    branch_match = re.search(
        r'"branches"\s*\{.*?"public"\s*\{.*?"buildid"\s*"([0-9]+)"',
        text_value,
        re.DOTALL,
    )
    if branch_match:
        return str(branch_match.group(1))
    patterns = [
        r'"buildid"\s*"([0-9]+)"',
        r'(?i)(?:version|buildid|build)\s*[:=]\s*([0-9]+(?:\.[0-9]+)*)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text_value)
        if match:
            return str(match.group(1))
    return None


def extract_steamcmd_appstate_build_ids(text: str) -> tuple[Optional[str], Optional[str]]:
    import re

    text_value = str(text or "")

    def _extract(pattern: str) -> Optional[str]:
        match = re.search(pattern, text_value, re.DOTALL)
        if not match:
            return None
        value = str(match.group(1) or "").strip()
        if not value or value == "0":
            return None
        return value

    current_build = _extract(r'"AppState"\s*\{.*?"buildid"\s*"([0-9]+)"')
    target_build = _extract(r'"AppState"\s*\{.*?"TargetBuildID"\s*"([0-9]+)"')
    if target_build is None:
        target_build = extract_steamcmd_target_version(text_value)
    return current_build, target_build


def _steamcmd_install_failure_message(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except Exception:
        return None

    for raw_line in text.splitlines():
        line = str(raw_line).strip()
        if not line:
            continue
        for marker in _STEAMCMD_INSTALL_FATAL_MARKERS:
            if marker.lower() in line.lower():
                return line
    return None


def _steamcmd_missing_configuration_retryable(message: Optional[str]) -> bool:
    text = str(message or "").strip().lower()
    return "missing configuration" in text


def wait_for_path_or_exit(
    path: str,
    proc,
    timeout_seconds: float,
    *,
    time_module=time,
    os_module=os,
) -> bool:
    deadline = time_module.monotonic() + float(timeout_seconds)
    while time_module.monotonic() < deadline:
        if os_module.path.exists(path):
            return True
        if proc is not None and proc.poll() is not None:
            break
    return os_module.path.exists(path)


def run_steamcmd_app_install(
    *,
    steam_app_id: str,
    server_dir: str,
    steamcmd_exe: str,
    cwd: str,
    logs_dir: str,
    instance_id: str,
    steamcmd_progress_metadata_name: str,
    steamcmd_native_console_log_path_fn,
    file_size_or_zero_fn,
    write_text_file_fn,
    write_json_file_fn,
    format_cmd_for_log_fn,
    install_server_timeout_seconds: float,
    install_server_log_tail_lines: int,
    tail_file_lines_fn,
    startupinfo,
    subprocess_module,
) -> dict:
    errors: List[str] = []
    warnings: List[str] = []

    log_path = os.path.join(logs_dir, "install_server.log")
    steamcmd_log_path = os.path.join(logs_dir, "steamcmd_install.log")
    progress_metadata_path = os.path.join(logs_dir, steamcmd_progress_metadata_name)
    runscript_path = os.path.join(logs_dir, "steamcmd_install_script.txt")
    steamcmd_native_log_path = steamcmd_native_console_log_path_fn(steamcmd_exe)
    steamcmd_native_log_offset = file_size_or_zero_fn(steamcmd_native_log_path)

    write_text_file_fn(
        runscript_path,
        "\n".join(
            [
                f'force_install_dir "{server_dir}"',
                "login anonymous",
                f"app_update {steam_app_id} validate",
                "quit",
                "",
            ]
        ),
    )
    write_json_file_fn(
        progress_metadata_path,
        {
            "instance_id": str(instance_id),
            "log_path": str(steamcmd_native_log_path),
            "source": "steamcmd_native_console_log",
            "start_offset": int(steamcmd_native_log_offset),
        },
    )

    argv = [steamcmd_exe, "+runscript", runscript_path]
    max_missing_configuration_retries = 1
    missing_configuration_retry_delay_seconds = 3.0

    try:
        with open(log_path, "w", encoding="utf-8") as log_handle:
            header_lines = [
                f"steam_install - app_id={steam_app_id} - SteamCMD (networked)",
                f"instance_id={instance_id}",
                f"server_dir={server_dir}",
                f"cwd={cwd}",
                format_cmd_for_log_fn(argv),
                f"steamcmd_log={steamcmd_log_path}",
                f"steamcmd_native_log={steamcmd_native_log_path}",
                f"steamcmd_native_log_offset={steamcmd_native_log_offset}",
                f"steamcmd_progress_metadata={progress_metadata_path}",
                "",
            ]
            log_handle.write("\n".join(header_lines))
            log_handle.flush()

        fatal_message = None
        returncode = 0
        for attempt_index in range(max_missing_configuration_retries + 1):
            attempt_number = attempt_index + 1
            with open(log_path, "a", encoding="utf-8") as log_handle:
                log_handle.write(f"attempt={attempt_number}\n")

            returncode = _steamcmd_run_command(
                argv,
                cwd=cwd,
                stdout_path=steamcmd_log_path,
                timeout_seconds=install_server_timeout_seconds,
                startupinfo=startupinfo,
                subprocess_module=subprocess_module,
            )
            fatal_message = _steamcmd_install_failure_message(steamcmd_log_path)
            with open(log_path, "a", encoding="utf-8") as log_handle:
                log_handle.write(f"attempt={attempt_number}; returncode={returncode}\n")
                if fatal_message:
                    log_handle.write(f"attempt={attempt_number}; fatal_message={fatal_message}\n")

            if fatal_message and _steamcmd_missing_configuration_retryable(fatal_message) and attempt_index < max_missing_configuration_retries:
                with open(log_path, "a", encoding="utf-8") as log_handle:
                    log_handle.write(
                        f"attempt={attempt_number}; retrying_after_seconds={missing_configuration_retry_delay_seconds}; "
                        "reason=Missing configuration\n"
                    )
                time.sleep(missing_configuration_retry_delay_seconds)
                continue
            break

        if fatal_message:
            errors.append(f"SteamCMD install failed: {fatal_message}")
            return {"ok": False, "details": "install_server failed (steamcmd fatal).", "warnings": warnings, "errors": errors}

        if returncode != 0:
            _tail_found, _tail_lines_list = tail_file_lines_fn(steamcmd_log_path, install_server_log_tail_lines)
            tail = "\n".join(_tail_lines_list)
            errors.append(f"SteamCMD failed with exit code {returncode}.")
            errors.append("steamcmd_install.log tail:\n" + tail)
            return {"ok": False, "details": "install_server failed (steamcmd non-zero).", "warnings": warnings, "errors": errors}

    except subprocess_module.TimeoutExpired:
        with open(log_path, "a", encoding="utf-8") as log_handle:
            log_handle.write(f"timeout_seconds={install_server_timeout_seconds}\nresult=timeout\n")
        with open(steamcmd_log_path, "a", encoding="utf-8") as steamcmd_log_handle:
            steamcmd_log_handle.write(f"\ntimeout_seconds={install_server_timeout_seconds}\n")
        errors.append(f"SteamCMD timed out after {install_server_timeout_seconds} seconds.")
        return {"ok": False, "details": "install_server failed (timeout).", "warnings": warnings, "errors": errors}

    except Exception as e:
        with open(log_path, "a", encoding="utf-8") as log_handle:
            log_handle.write(f"result=error: {e}\n")
        with open(steamcmd_log_path, "a", encoding="utf-8") as steamcmd_log_handle:
            steamcmd_log_handle.write(f"\nresult=error: {e}\n")
        errors.append(f"SteamCMD execution error: {e}")
        return {"ok": False, "details": "install_server failed (exception).", "warnings": warnings, "errors": errors}

    return {"ok": True, "details": "steamcmd install complete.", "warnings": warnings, "errors": errors}


def run_steamcmd_version_check(
    *,
    steam_app_id: str,
    steamcmd_exe: str,
    cwd: str,
    logs_dir: str,
    write_text_file_fn,
    extract_steamcmd_target_version_fn,
    steamcmd_startupinfo_fn,
    subprocess_module,
) -> Tuple[Optional[str], List[str]]:
    warnings: List[str] = []
    target_version: Optional[str] = None

    runscript_path = os.path.join(str(logs_dir), "steamcmd_check_update_script.txt")
    probe_log_path = os.path.join(str(logs_dir), "check_update.log")
    write_text_file_fn(
        runscript_path,
        "\n".join(
            [
                "login anonymous",
                "app_info_update 1",
                f"app_info_print {steam_app_id}",
                "quit",
                "",
            ]
        ),
    )
    try:
        _steamcmd_run_command(
            [steamcmd_exe, "+runscript", runscript_path],
            cwd=cwd,
            stdout_path=probe_log_path,
            timeout_seconds=30.0,
            startupinfo=steamcmd_startupinfo_fn(),
            subprocess_module=subprocess_module,
        )
        try:
            with open(probe_log_path, "r", encoding="utf-8", errors="replace") as handle:
                probe_text = handle.read()
        except Exception as e:
            warnings.append(f"Unable to read update probe log: {e}")
            probe_text = ""
        target_version = extract_steamcmd_target_version_fn(probe_text)
        if target_version is None:
            warnings.append("Unable to determine target version from SteamCMD app info.")
    except subprocess_module.TimeoutExpired:
        warnings.append("SteamCMD update check timed out.")
    except Exception as e:
        warnings.append(f"SteamCMD update check failed: {e}")

    return target_version, warnings
