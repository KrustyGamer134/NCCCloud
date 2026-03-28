from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from core.version_build_store import (
    load_version_build_plugins_state,
    resolve_version_build_map_path,
    save_version_build_plugins_state,
)


class PluginHandler:

    def __init__(self, plugin_json: dict, plugin_dir: str, cluster_root: str, plugin_key: str | None = None):
        self._plugin = plugin_json
        self._plugin_dir = plugin_dir
        self._cluster_root = cluster_root
        resolved_key = str(plugin_key or "").strip()
        if not resolved_key:
            resolved_key = str(os.path.basename(str(plugin_dir or "")).strip() or plugin_json.get("name") or "")
        self._plugin_key = resolved_key
        self._processes: dict = {}  # instance_id -> subprocess.Popen

    # ------------------------------------------------------------------
    # Public dispatch
    # ------------------------------------------------------------------

    def handle(self, action: str, payload: dict) -> dict:
        payload = payload or {}
        dispatch = {
            "shutdown":         self._handle_shutdown,
            "get_capabilities": self._handle_get_capabilities,
            "get_port_specs":   self._handle_get_port_specs,
            "discover_servers": self._handle_discover_servers,
            "install_deps":     self._handle_install_deps,
            "install_server":   self._handle_install_server,
            "check_update":     self._handle_check_update,
            "runtime_status":   self._handle_runtime_status,
            "runtime_summary":  self._handle_runtime_summary,
            "start":            self._handle_start,
            "stop":             self._handle_stop,
            "graceful_stop":    self._handle_stop,
            "rcon_exec":        self._handle_rcon_exec,
            "sync_ini_fields":  self._handle_sync_ini_fields,
            "validate":         self._handle_validate,
        }
        fn = dispatch.get(action)
        if fn is None:
            return {"status": "error", "data": {"message": f"Unknown action: {action}"}}
        return fn(payload)

    # ------------------------------------------------------------------
    # Fully wired actions
    # ------------------------------------------------------------------

    def _handle_shutdown(self, payload: dict) -> dict:
        return {"status": "success", "data": {"ok": True}}

    def _handle_get_capabilities(self, payload: dict) -> dict:
        return {"status": "success", "data": self._plugin}

    def _handle_get_port_specs(self, payload: dict) -> dict:
        instance_id = str(payload.get("instance_id") or "")
        required_ports = self._plugin.get("required_ports") or []
        requested = payload.get("requested_ports")

        # requested_ports path: caller supplies port values directly (used during configure)
        if requested is not None:
            try:
                port_values = [int(x) for x in requested]
            except Exception:
                return {"status": "error", "data": {"ok": False, "ports": [], "errors": ["requested_ports must be a list of ints"]}}
            ports = []
            for idx, spec in enumerate(required_ports):
                entry: Dict[str, Any] = {"name": spec.get("name", ""), "proto": spec.get("proto", "")}
                if idx < len(port_values):
                    entry["port"] = port_values[idx]
                ports.append(entry)
            return {"status": "success", "data": {"ok": True, "ports": ports, "warnings": [], "errors": []}}

        # instance_id path: read from existing instance config
        inst = self._load_instance_config(instance_id)
        ports = []
        for spec in required_ports:
            name = spec.get("name", "")
            proto = spec.get("proto", "")
            value = inst.get(f"{name}_port") if inst else None
            entry = {"name": name, "proto": proto}
            if value is not None:
                entry["port"] = int(value)
            ports.append(entry)

        return {"status": "success", "data": {"ports": ports}}

    def _handle_discover_servers(self, payload: dict) -> dict:
        roots = self._candidate_discovery_roots()
        if not roots:
            return {
                "status": "error",
                "data": {
                    "ok": False,
                    "details": "Discovery root is not configured. Set GameServers Root and Plugin Install Root first.",
                    "candidates": [],
                },
            }

        existing_roots = [root for root in roots if os.path.isdir(root)]
        if not existing_roots:
            return {
                "status": "error",
                "data": {
                    "ok": False,
                    "details": f"Discovery root does not exist: {roots[0]}",
                    "candidates": [],
                },
            }

        candidates = []
        seen = set()
        for root in existing_roots:
            for path in self._iter_discovery_install_paths(root):
                normalized = os.path.normcase(os.path.abspath(path))
                if normalized in seen:
                    continue
                seen.add(normalized)
                candidates.append(self._build_discovery_candidate(path))
        candidates = [item for item in candidates if isinstance(item, dict)]
        return {"status": "success", "data": {"ok": True, "candidates": candidates}}

    def _handle_install_deps(self, payload: dict) -> dict:
        instance_id = str(payload.get("instance_id") or "")
        warnings: list[str] = []
        errors: list[str] = []

        layout = self._resolve_layout(instance_id)
        if not layout:
            return {"status": "error", "data": {"ok": False, "errors": ["Layout could not be resolved."], "warnings": [], "details": "install_deps failed"}}

        created = self._create_dirs(layout)
        return {
            "status": "success",
            "data": {
                "ok": True,
                "details": "install_deps complete (layout created; no downloads performed).",
                "warnings": warnings,
                "errors": errors,
                "created": created,
            },
        }

    def _handle_install_server(self, payload: dict) -> dict:
        from core.steam_installer import run_steamcmd_app_install, run_steamcmd_version_check, extract_steamcmd_target_version

        instance_id = str(payload.get("instance_id") or "")
        install_target = self._install_target(payload)
        warnings: list[str] = []
        errors: list[str] = []

        steam_app_id = str(self._plugin.get("steam_app_id") or "")
        if not steam_app_id:
            errors.append("steam_app_id not configured in plugin.json.")
            return {"status": "error", "data": {"ok": False, "errors": errors, "warnings": warnings, "details": "install_server failed"}}

        layout = self._resolve_layout(instance_id) if install_target == "instance" else self._resolve_master_layout()
        if not layout:
            errors.append("Layout could not be resolved.")
            return {"status": "error", "data": {"ok": False, "errors": errors, "warnings": warnings, "details": "install_server failed"}}

        created = self._create_dirs(layout)
        install_root = layout.get("install_root") or ""
        server_dir = created.get("server_dir") or str(install_root)
        logs_dir = created.get("logs_dir") or str(install_root)

        steamcmd_exe = self._resolve_steamcmd_exe(layout)
        if not steamcmd_exe:
            errors.append("SteamCMD not ready. Complete app setup in App Settings and install SteamCMD under the configured steamcmd_root before continuing.")
            return {"status": "error", "data": {"ok": False, "errors": errors, "warnings": warnings, "details": "install_server failed"}}

        steamcmd_dir = str(layout.get("steamcmd_dir") or "")
        cwd = steamcmd_dir if steamcmd_dir and os.path.isdir(steamcmd_dir) else str(install_root)

        from core.steamcmd import startupinfo as _steamcmd_startupinfo
        startupinfo = _steamcmd_startupinfo(is_windows_fn=lambda: os.name == "nt", subprocess_module=subprocess)

        result = run_steamcmd_app_install(
            steam_app_id=steam_app_id,
            server_dir=server_dir,
            steamcmd_exe=steamcmd_exe,
            cwd=cwd,
            logs_dir=logs_dir,
            instance_id=instance_id,
            steamcmd_progress_metadata_name="steamcmd_progress_source.json",
            steamcmd_native_console_log_path_fn=self._steamcmd_native_console_log_path,
            file_size_or_zero_fn=self._file_size_or_zero,
            write_text_file_fn=self._write_text_file,
            write_json_file_fn=self._write_json_file,
            format_cmd_for_log_fn=self._format_cmd_for_log,
            install_server_timeout_seconds=float(payload.get("timeout_seconds") or 7200),
            install_server_log_tail_lines=int(payload.get("log_tail_lines") or 50),
            tail_file_lines_fn=self._tail_file_lines,
            startupinfo=startupinfo,
            subprocess_module=subprocess,
        )

        if not result["ok"]:
            return {"status": "error", "data": result}

        exe_rel = str(self._plugin.get("executable") or "")
        exe_path = os.path.join(server_dir, exe_rel.replace("/", os.sep).replace("\\", os.sep)) if server_dir and exe_rel else ""
        if not exe_path or not os.path.isfile(exe_path):
            return {
                "status": "error",
                "data": {
                    "ok": False,
                    "details": f"Server executable not found: {exe_path}",
                    "warnings": list(result.get("warnings") or []),
                    "errors": [f"Server executable not found: {exe_path}"],
                },
            }

        # Write INI from ini_settings after successful install
        ini_warnings = self._write_ini_settings(instance_id, server_dir)
        warnings.extend(result.get("warnings", []))
        warnings.extend(ini_warnings)

        master_current_build_id = None
        master_current_version = None
        if install_target == "master":
            from core.steamcmd import startupinfo as _steamcmd_startupinfo

            target_build_id, update_warnings = run_steamcmd_version_check(
                steam_app_id=steam_app_id,
                steamcmd_exe=steamcmd_exe,
                cwd=cwd,
                logs_dir=logs_dir,
                write_text_file_fn=self._write_text_file,
                extract_steamcmd_target_version_fn=extract_steamcmd_target_version,
                steamcmd_startupinfo_fn=lambda: _steamcmd_startupinfo(is_windows_fn=lambda: os.name == "nt", subprocess_module=subprocess),
                subprocess_module=subprocess,
            )
            warnings.extend(update_warnings)
            master_current_build_id = self._normalize_build_id(target_build_id)
            master_current_version = self._read_master_version_text(server_dir, logs_dir)
            self._persist_trusted_master_build_state(
                plugin_name=self._version_build_plugin_key(),
                master_current_build_id=master_current_build_id,
                master_current_version=None,
            )

        return {
            "status": "success",
            "data": {
                "ok": True,
                "details": f"install_server complete (app {steam_app_id} installed/updated).",
                "install_target": install_target,
                "install_root": str(server_dir),
                "current_build_id": master_current_build_id,
                "master_current_version": master_current_version,
                "warnings": warnings,
                "errors": [],
            },
        }

    def _handle_check_update(self, payload: dict) -> dict:
        from core.steam_installer import (
            run_steamcmd_version_check,
            extract_steamcmd_target_version,
            extract_steamcmd_appstate_build_ids,
        )

        instance_id = str(payload.get("instance_id") or "")
        install_target = self._install_target(payload)
        warnings: list[str] = []

        steam_app_id = str(self._plugin.get("steam_app_id") or "")
        layout = self._resolve_layout(instance_id) if install_target == "instance" else self._resolve_master_layout()
        if not layout:
            return {"status": "success", "data": {"ok": True, "target_version": None, "warnings": ["Layout could not be resolved."], "errors": []}}

        steamcmd_exe = self._resolve_steamcmd_exe(layout)
        if not steamcmd_exe:
            return {"status": "success", "data": {"ok": True, "target_version": None, "warnings": ["SteamCMD not found."], "errors": []}}

        created = self._create_dirs(layout)
        logs_dir = created.get("logs_dir") or str(layout.get("install_root") or "")
        install_root = layout.get("install_root") or ""
        steamcmd_dir = str(layout.get("steamcmd_dir") or "")
        cwd = steamcmd_dir if steamcmd_dir and os.path.isdir(steamcmd_dir) else str(install_root)

        from core.steamcmd import startupinfo as _steamcmd_startupinfo
        target_version, new_warnings = run_steamcmd_version_check(
            steam_app_id=steam_app_id,
            steamcmd_exe=steamcmd_exe,
            cwd=cwd,
            logs_dir=logs_dir,
            write_text_file_fn=self._write_text_file,
            extract_steamcmd_target_version_fn=extract_steamcmd_target_version,
            steamcmd_startupinfo_fn=lambda: _steamcmd_startupinfo(is_windows_fn=lambda: os.name == "nt", subprocess_module=subprocess),
            subprocess_module=subprocess,
        )
        warnings.extend(new_warnings)
        current_build_id = None
        probe_log_path = os.path.join(str(logs_dir), "check_update.log")
        try:
            probe_text = Path(probe_log_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            probe_text = ""
        parsed_current_build_id, parsed_target_build_id = extract_steamcmd_appstate_build_ids(probe_text)
        if parsed_target_build_id:
            target_version = parsed_target_build_id
        current_build_id = self._normalize_build_id(parsed_current_build_id)
        master_current_version = self._read_master_version_text(
            str(layout.get("server_dir") or layout.get("install_root") or "").strip(),
            str(logs_dir),
        )
        stored_state = self._load_version_build_state().get(self._version_build_plugin_key(), {})
        if not isinstance(stored_state, dict):
            stored_state = {}
        if not current_build_id:
            current_build_id = self._normalize_build_id(stored_state.get("master_current_build_id"))
        if current_build_id and not master_current_version:
            master_current_version = self._version_for_stored_build(self._version_build_plugin_key(), current_build_id)
        self._persist_trusted_master_build_state(
            plugin_name=self._version_build_plugin_key(),
            master_current_build_id=current_build_id,
            master_current_version=None,
        )
        return {
            "status": "success",
            "data": {
                "ok": True,
                "current_build_id": current_build_id,
                "target_version": target_version,
                "master_current_version": master_current_version,
                "install_target": install_target,
                "install_root": str(layout.get("install_root") or ""),
                "warnings": warnings,
                "errors": [],
            },
        }

    @staticmethod
    def _normalize_build_id(value: object) -> Optional[str]:
        text = str(value or "").strip()
        return text if text.isdigit() and text != "0" else None

    def _read_master_version_text(self, server_dir: str, logs_dir: str) -> Optional[str]:
        master_current_version = None
        install_log_path = os.path.join(str(logs_dir), "install_server.log")
        found, install_tail = self._tail_file_lines(install_log_path, 200)
        if found:
            text = "\n".join(str(line) for line in (install_tail or []))
            for pattern in (
                r"(?i)\bInstalled\s+server\s+version\s*:\s*([0-9]+(?:\.[0-9]+)*)",
                r"(?i)\bARK\s+Version\s*:\s*([0-9]+(?:\.[0-9]+)*)",
            ):
                match = re.search(pattern, text)
                if match:
                    master_current_version = str(match.group(1))
                    break
        if not master_current_version:
            executable_rel = str(self._plugin.get("executable") or "").strip()
            if server_dir and executable_rel:
                executable_path = os.path.join(
                    server_dir,
                    executable_rel.replace("/", os.sep).replace("\\", os.sep),
                )
                master_current_version = self._read_executable_version(executable_path)
        return str(master_current_version or "").strip() or None

    def _version_build_map_path(self) -> str:
        cluster_cfg = self._load_cluster_config()
        return str(
            resolve_version_build_map_path(
                cluster_root=str(self._cluster_root or ""),
                gameservers_root=str(cluster_cfg.get("gameservers_root") or ""),
            )
            or ""
        )

    def _version_build_plugin_key(self) -> str:
        return str(self._plugin_key or self._plugin.get("name") or "").strip()

    def _load_version_build_state(self) -> dict:
        return load_version_build_plugins_state(self._version_build_map_path())

    def _save_version_build_state(self, plugins: dict) -> None:
        save_version_build_plugins_state(self._version_build_map_path(), plugins)

    def _version_for_stored_build(self, plugin_name: str, build_id: str) -> Optional[str]:
        plugin_state = self._load_version_build_state().get(str(plugin_name or "").strip(), {})
        if not isinstance(plugin_state, dict):
            return None
        builds = plugin_state.get("builds") if isinstance(plugin_state.get("builds"), dict) else plugin_state
        if not isinstance(builds, dict):
            return None
        value = builds.get(str(build_id or "").strip())
        text = str(value or "").strip()
        return text or None

    def _persist_trusted_master_build_state(self, plugin_name: str, master_current_build_id: Optional[str], master_current_version: Optional[str]) -> None:
        plugin_text = str(plugin_name or "").strip()
        build_text = self._normalize_build_id(master_current_build_id)
        version_text = str(master_current_version or "").strip()
        if not plugin_text or not build_text:
            return
        plugins = self._load_version_build_state()
        plugin_state = plugins.get(plugin_text)
        if not isinstance(plugin_state, dict):
            plugin_state = {}
        plugin_builds = plugin_state.get("builds")
        if isinstance(plugin_builds, dict):
            raw_builds: dict[str, str] = {
                str(key): str(value)
                for key, value in plugin_builds.items()
            }
        else:
            raw_builds = {
                str(key): str(value)
                for key, value in plugin_state.items()
                if self._normalize_build_id(key) and str(value or "").strip()
            }
        builds = {str(key): str(value) for key, value in raw_builds.items() if self._normalize_build_id(key) and str(value or "").strip()}
        existing_version = str(builds.get(build_text) or "").strip()
        plugin_state["master_current_build_id"] = build_text
        if existing_version and version_text and existing_version != version_text:
            plugin_state["builds"] = dict(builds)
            plugins[plugin_text] = plugin_state
            self._save_version_build_state(plugins)
            return
        if version_text and not existing_version:
            builds[build_text] = version_text
        plugin_state["builds"] = builds
        plugins[plugin_text] = plugin_state
        self._save_version_build_state(plugins)

    def _read_executable_version(self, executable_path: str) -> Optional[str]:
        path = str(executable_path or "").strip()
        if not path or not os.path.isfile(path) or os.name != "nt":
            return None
        quoted_path = path.replace("'", "''")
        try:
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(Get-Item -LiteralPath '{quoted_path}').VersionInfo.ProductVersion",
                ],
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )
        except Exception:
            return None
        candidates = [str(completed.stdout or "").strip(), str(completed.stderr or "").strip()]
        for text in candidates:
            if not text:
                continue
            match = re.search(r"([0-9]+(?:\.[0-9]+)+)", text)
            if match:
                return str(match.group(1))
        return None

    # ------------------------------------------------------------------
    # Wired actions (Step 3)
    # ------------------------------------------------------------------

    def _handle_start(self, payload: dict) -> dict:
        from core.launcher import (
            compute_effective_active_mods,
            compute_effective_passive_mods,
            server_launch_creationflags,
            spawn_server_process,
        )
        instance_id = str(payload.get("instance_id") or "")
        defaults = self._load_defaults()
        inst = self._load_instance_config(instance_id) or {}
        layout = self._resolve_layout(instance_id)
        if not layout:
            return {"status": "error", "data": {"ok": False, "errors": ["Layout could not be resolved."], "warnings": [], "simulated": False}}

        server_dir = str(layout.get("server_dir") or "")
        exe_rel = str(self._plugin.get("executable") or "")
        exe_path = os.path.abspath(
            os.path.join(server_dir, exe_rel.replace("/", os.sep).replace("\\", os.sep))
        ) if server_dir and exe_rel else None

        if not exe_path or not os.path.exists(exe_path):
            return {"status": "error", "data": {"ok": False, "errors": [f"Server executable not found: {exe_path}"], "warnings": [], "simulated": False}}

        active_mods = compute_effective_active_mods(defaults, inst)
        passive_mods = compute_effective_passive_mods(defaults, inst)
        map_val = str(inst.get("map") or defaults.get("map") or "")
        cluster_id = str(inst.get("cluster_id") or defaults.get("cluster_id") or "").strip()
        cluster_dir_override = self._derive_cluster_dir_override(defaults)
        launch_context = {
            "python": sys.executable,
            "executable": str(exe_path),
            "map": map_val,
            "cluster_id": cluster_id,
            "cluster_dir_override": cluster_dir_override,
            "mods": ",".join(active_mods),
            "passive_mods": ",".join(passive_mods),
            "game_port": str(inst.get("game_port") or defaults.get("game_port") or ""),
            "rcon_port": str(inst.get("rcon_port") or defaults.get("rcon_port") or ""),
            "admin_password": str(inst.get("admin_password") or defaults.get("admin_password") or ""),
            "server_name": str(inst.get("server_name") or defaults.get("server_name") or ""),
            "map_mod": str(inst.get("map_mod") or defaults.get("map_mod") or ""),
        }
        argv = self._build_launch_argv(
            exe_path=str(exe_path),
            map_val=map_val,
            cluster_id=cluster_id,
            cluster_dir_override=cluster_dir_override,
            active_mods=active_mods,
            passive_mods=passive_mods,
            launch_context=launch_context,
        )
        cwd = os.path.abspath(server_dir) if server_dir and os.path.isdir(server_dir) else os.path.dirname(exe_path)
        start_ready_signal = str(self._plugin.get("start_ready_signal") or "").strip()

        try:
            proc = spawn_server_process(
                argv,
                cwd=cwd,
                creationflags=0 if start_ready_signal else server_launch_creationflags(),
                stdout=subprocess.PIPE if start_ready_signal else None,
                stderr=subprocess.STDOUT if start_ready_signal else None,
                text=bool(start_ready_signal),
                subprocess_module=subprocess,
            )
            if start_ready_signal:
                ready_ok, ready_error = self._await_start_ready_signal(proc, start_ready_signal)
                if not ready_ok:
                    terminate = getattr(proc, "terminate", None)
                    if callable(terminate):
                        try:
                            terminate()
                        except Exception:
                            pass
                    return {
                        "status": "error",
                        "data": {"ok": False, "errors": [ready_error or "start readiness check failed"], "warnings": [], "simulated": False},
                    }
            self._set_proc(instance_id, proc)
            pid = getattr(proc, "pid", None)
            paths = self._resolve_runtime_paths(layout, instance_id)
            if paths.get("pid_file") and pid is not None:
                self._write_pid_file(paths["pid_file"], int(pid))
            return {"status": "success", "data": {"ok": True, "pid": pid, "simulated": False, "warnings": [], "errors": []}}
        except Exception as e:
            return {"status": "error", "data": {"ok": False, "errors": [str(e)], "warnings": [], "simulated": False}}

    def _handle_rcon_exec(self, payload: dict) -> dict:
        import socket
        import struct
        from core.rcon_client import GenericRconClient

        instance_id = str(payload.get("instance_id") or "")
        command = str(payload.get("command") or "").strip()
        if not command:
            return {"status": "error", "data": {"ok": False, "errors": ["command is required"], "warnings": []}}

        rcon_cfg = self._plugin.get("rcon") or {}
        defaults = self._load_defaults()
        inst = self._load_instance_config(instance_id) or {}
        host = str(rcon_cfg.get("host") or "127.0.0.1")
        rcon_port = self._rcon_port(instance_id, rcon_cfg)
        password = self._effective_admin_password(defaults, inst)
        rcon_enabled = self._effective_rcon_enabled(defaults, inst)

        if not rcon_enabled:
            return {"status": "error", "data": {"ok": False, "errors": ["RCON not configured: disabled"], "warnings": []}}
        if rcon_port is None:
            return {"status": "error", "data": {"ok": False, "errors": ["RCON not configured: missing rcon_port"], "warnings": []}}
        if not password:
            return {"status": "error", "data": {"ok": False, "errors": ["RCON not configured: missing admin_password"], "warnings": []}}

        try:
            client = GenericRconClient(
                host=host,
                port=rcon_port,
                password=password,
                socket_module=socket,
                struct_module=struct,
                auth_packet_type=3,
                command_packet_type=2,
            )
            response = client.exec(command)
            return {
                "status": "success",
                "data": {"ok": True, "details": response or "OK", "warnings": [], "errors": []},
            }
        except Exception as exc:
            return {"status": "error", "data": {"ok": False, "errors": [str(exc)], "warnings": []}}

    def _handle_stop(self, payload: dict) -> dict:
        import socket
        import struct
        from core.rcon import perform_graceful_stop
        from core.rcon_client import GenericRconClient
        instance_id = str(payload.get("instance_id") or "")
        layout = self._resolve_layout(instance_id)
        if not layout:
            return {"status": "error", "data": {"ok": False, "errors": ["Layout could not be resolved."], "warnings": []}}

        paths = self._resolve_runtime_paths(layout, instance_id)
        rcon_cfg = self._plugin.get("rcon") or {}
        stop_sequence = list(rcon_cfg.get("commands", {}).get("stop") or [])
        defaults = self._load_defaults()
        inst = self._load_instance_config(instance_id) or {}

        def _build_rcon_client(iid):
            host = str(rcon_cfg.get("host") or "127.0.0.1")
            rcon_port = self._rcon_port(iid, rcon_cfg)
            password = self._effective_admin_password(defaults, inst)
            rcon_enabled = self._effective_rcon_enabled(defaults, inst)
            if not rcon_enabled:
                return None, "RCON not configured: disabled"
            if rcon_port is None:
                return None, "RCON not configured: missing rcon_port"
            if not password:
                return None, "RCON not configured: missing admin_password"
            return GenericRconClient(
                host=host,
                port=rcon_port,
                password=password,
                socket_module=socket,
                struct_module=struct,
                auth_packet_type=3,
                command_packet_type=2,
            ), None

        result = perform_graceful_stop(
            instance_id,
            layout,
            stop_sequence=stop_sequence,
            pid_file_path_fn=lambda _layout, iid: paths["pid_file"],
            get_proc_fn=self._get_proc,
            load_plugin_defaults_fn=self._load_defaults,
            resolve_rcon_target_fn=lambda iid: (
                str(rcon_cfg.get("host") or "127.0.0.1"),
                self._rcon_port(iid, rcon_cfg),
            ),
            build_rcon_client_fn=_build_rcon_client,
            source_rcon_client_cls=None,
            proc_is_running_fn=self._proc_is_running,
            wait_or_kill_fn=self._wait_or_kill,
            clear_proc_fn=self._clear_proc,
            remove_pid_file_fn=self._remove_pid_file,
            log_rcon_send_fn=lambda iid, host, port, cmd: None,
            defaults=defaults,
            inst=inst,
            fallback_pid_fn=lambda: self._read_pid_file(paths["pid_file"]),
        )
        status = "success" if result.get("ok") else "error"
        return {"status": status, "data": result}

    def _handle_runtime_status(self, payload: dict) -> dict:
        from core.runtime_monitor import runtime_status_payload
        instance_id = str(payload.get("instance_id") or "")
        result = self._build_runtime_payload(
            instance_id,
            builder_fn=runtime_status_payload,
            extract_version_token_fn=self._extract_runtime_version_value,
            extract_running_version_fn=lambda lines: None,
        )
        return {"status": "success", "data": result}

    def _handle_runtime_summary(self, payload: dict) -> dict:
        from core.runtime_monitor import runtime_summary_payload
        instance_id = str(payload.get("instance_id") or "")
        result = self._build_runtime_payload(
            instance_id,
            builder_fn=runtime_summary_payload,
            extract_version_token_fn=self._extract_runtime_version_value,
            extract_running_version_fn=self._extract_runtime_version_value,
        )
        return {"status": "success", "data": result}

    def _build_runtime_payload(
        self,
        instance_id: str,
        *,
        builder_fn,
        extract_version_token_fn,
        extract_running_version_fn,
    ) -> dict:
        kwargs = self._build_monitor_kwargs(instance_id)
        return builder_fn(
            instance_id,
            **kwargs,
            tail_file_lines_fn=self._tail_file_lines,
            extract_version_token_fn=extract_version_token_fn,
            extract_running_version_fn=extract_running_version_fn,
            ready_signal=str(self._plugin.get("ready_signal") or ""),
            status_log_tail_lines=400,
            version_log_tail_lines=200,
        )

    @staticmethod
    def _extract_runtime_version_value(lines):
        import re

        text = "\n".join(str(line) for line in (lines or []))
        for pattern in (
            r"(?i)\bInstalled\s+server\s+version\s*:\s*([0-9]+(?:\.[0-9]+)*)",
            r"(?i)\bARK\s+Version\s*:\s*([0-9]+(?:\.[0-9]+)*)",
        ):
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _await_start_ready_signal(proc, ready_signal: str) -> tuple[bool, Optional[str]]:
        stream = getattr(proc, "stdout", None)
        if stream is None:
            return False, "start readiness check failed: stdout unavailable"
        seen: list[str] = []
        try:
            while True:
                line = stream.readline()
                if not line:
                    detail = ""
                    if seen:
                        detail = f" output={' | '.join(item.strip() for item in seen if item.strip())}"
                    if proc.poll() is None:
                        return False, f"start readiness check failed: missing ready signal '{ready_signal}'{detail}"
                    return False, f"start failed before ready signal '{ready_signal}'{detail}"
                seen.append(str(line))
                if ready_signal in str(line):
                    return True, None
        except Exception as exc:
            return False, str(exc)

    def _build_launch_argv(
        self,
        *,
        exe_path: str,
        map_val: str,
        cluster_id: str,
        cluster_dir_override: str,
        active_mods,
        passive_mods,
        launch_context: dict[str, str],
    ) -> list[str]:
        launch_prefix = list(self._plugin.get("launch_prefix") or [])
        launch_args = list(self._plugin.get("launch_args") or [])
        if launch_prefix or launch_args:
            argv = [self._format_launch_token(token, launch_context) for token in launch_prefix]
            argv.append(str(exe_path))
            argv.extend(
                formatted
                for formatted in (
                    self._format_launch_token(token, launch_context)
                    for token in launch_args
                )
                if formatted
            )
            return argv

        argv = [str(exe_path)]
        if map_val:
            argv.append(map_val)
        if cluster_id:
            argv.append(f"-clusterID={cluster_id}")
        if cluster_dir_override:
            argv.append(f"-ClusterDirOverride={cluster_dir_override}")
        if active_mods:
            argv.append(f"-mods={','.join(active_mods)}")
        if passive_mods:
            argv.append(f"-passivemods={','.join(passive_mods)}")
        return argv

    @staticmethod
    def _format_launch_token(token: object, context: dict[str, str]) -> str:
        text = str(token)
        for key, value in context.items():
            text = text.replace("{" + str(key) + "}", str(value))
        return text.strip()

    def _handle_validate(self, payload: dict) -> dict:
        instance_id = str(payload.get("instance_id") or "")
        errors: list[str] = []
        warnings: list[str] = []

        layout = self._resolve_layout(instance_id)
        steamcmd_exe = self._resolve_steamcmd_exe(layout) if layout else None
        if not steamcmd_exe:
            warnings.append("SteamCMD not found.")

        install_root = layout.get("install_root") if layout else None
        if not install_root:
            errors.append("Install root not configured.")

        inst = self._load_instance_config(instance_id) or {}
        defaults = self._load_defaults()
        required = ["map", "game_port", "rcon_port", "admin_password"]
        for field in required:
            val = inst.get(field) or defaults.get(field)
            if not val:
                errors.append(f"Required field not set: {field}")

        if install_root and os.path.isdir(str(install_root)):
            server_dir = str((layout or {}).get("server_dir") or "")
            exe_rel = str(self._plugin.get("executable") or "")
            if server_dir and exe_rel:
                exe_path = os.path.join(server_dir, exe_rel.replace("/", os.sep).replace("\\", os.sep))
                if not os.path.exists(exe_path):
                    warnings.append(f"Server executable not found: {exe_path}")

        ok = len(errors) == 0
        return {
            "status": "success" if ok else "error",
            "data": {"ok": ok, "errors": errors, "warnings": warnings},
        }

    def _handle_sync_ini_fields(self, payload: dict) -> dict:
        instance_id = str(payload.get("instance_id") or "")
        requested_fields = payload.get("fields")
        field_names = [str(item).strip() for item in list(requested_fields or []) if str(item).strip()]
        layout = self._resolve_layout(instance_id)
        if not layout:
            return {"status": "error", "data": {"ok": False, "errors": ["Layout could not be resolved."], "warnings": []}}
        server_dir = str(layout.get("server_dir") or "")
        if not server_dir or not os.path.isdir(server_dir):
            return {"status": "success", "data": {"ok": True, "warnings": [], "errors": []}}
        warnings = self._write_ini_settings(instance_id, server_dir, field_names=field_names)
        return {"status": "success", "data": {"ok": True, "warnings": warnings, "errors": []}}

    # ------------------------------------------------------------------
    # Process registry helpers
    # ------------------------------------------------------------------

    def _get_proc(self, instance_id: str):
        return self._processes.get(str(instance_id))

    def _set_proc(self, instance_id: str, proc) -> None:
        self._processes[str(instance_id)] = proc

    def _clear_proc(self, instance_id: str) -> None:
        self._processes.pop(str(instance_id), None)

    def _proc_is_running(self, proc) -> bool:
        if proc is None:
            return False
        try:
            return proc.poll() is None
        except Exception:
            return False

    def _wait_or_kill(self, proc):
        if proc is None:
            return True, False
        if proc.poll() is not None:
            return True, False
        stop_wait = float(self._plugin.get("stop_wait_seconds") or 60.0)
        try:
            proc.wait(timeout=stop_wait)
            return True, False
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=stop_wait)
            return True, True

    def _read_pid_file(self, path: str):
        from core.process import read_pid_file as _core_read_pid_file
        return _core_read_pid_file(path)

    def _write_pid_file(self, path: str, pid: int) -> None:
        from core.process import write_pid_file as _core_write_pid_file
        _core_write_pid_file(self._write_text_file, path, pid)

    def _remove_pid_file(self, path: str) -> None:
        from core.process import remove_pid_file as _core_remove_pid_file
        _core_remove_pid_file(path)

    def _rcon_port(self, instance_id: str, rcon_cfg: dict):
        port_field = str(rcon_cfg.get("port_field") or "rcon_port")
        inst = self._load_instance_config(instance_id) or {}
        val = inst.get(port_field)
        if val is None:
            return None
        try:
            return int(val)
        except Exception:
            return None

    def _resolve_runtime_paths(self, layout: dict, instance_id: str) -> dict:
        logs_dir = str(layout.get("logs_dir") or "")
        server_log_path = str(self._plugin.get("server_log_path") or "")
        server_dir = str(layout.get("server_dir") or "")
        if server_log_path and server_dir:
            server_log = os.path.join(server_dir, server_log_path.replace("/", os.sep).replace("\\", os.sep))
        else:
            server_log = os.path.join(logs_dir, "server.log") if logs_dir else ""
        return {
            "pid_file": os.path.join(logs_dir, "server.pid") if logs_dir else "",
            "server_log": server_log,
            "install_server_log": os.path.join(logs_dir, "install_server.log") if logs_dir else "",
            "steamcmd_install_log": os.path.join(logs_dir, "steamcmd_install.log") if logs_dir else "",
            "instance_id": instance_id,
        }

    def _tasklist_first_matching_pid(self):
        process_names = [str(n) for n in (self._plugin.get("process_names") or [])]
        from core.process import tasklist_first_pid as _core_tasklist_first_pid
        return _core_tasklist_first_pid(
            timeout_seconds=2.0,
            process_names=process_names,
            subprocess_module=subprocess,
        )

    def _build_monitor_kwargs(self, instance_id: str) -> dict:
        def resolve_effective_layout_fn(iid):
            defaults = self._load_defaults()
            inst = self._load_instance_config(iid) or {}
            layout = self._resolve_layout(iid) or {}
            return defaults, inst, layout

        def resolve_effective_server_name_fn(defaults, inst):
            return self._effective_server_name(defaults, inst)

        def resolve_runtime_paths_fn(layout, iid):
            return self._resolve_runtime_paths(layout, iid)

        from core.process import tasklist_pid_running as _core_tasklist_pid_running
        return {
            "resolve_effective_layout_fn": resolve_effective_layout_fn,
            "resolve_effective_server_name_fn": resolve_effective_server_name_fn,
            "resolve_runtime_paths_fn": resolve_runtime_paths_fn,
            "get_proc_fn": self._get_proc,
            "proc_is_running_fn": self._proc_is_running,
            "read_pid_file_fn": self._read_pid_file,
            "tasklist_pid_running_fn": lambda pid: _core_tasklist_pid_running(
                pid, timeout_seconds=2.0, subprocess_module=subprocess
            ),
            "tasklist_first_ark_pid_fn": self._tasklist_first_matching_pid,
        }

    # ------------------------------------------------------------------
    # Layout / path helpers
    # ------------------------------------------------------------------

    def _load_cluster_config(self) -> dict:
        import json
        if not self._cluster_root:
            return {}
        for name in ("cluster_config.json", os.path.join("config", "cluster_config.json")):
            path = os.path.join(str(self._cluster_root), name)
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8-sig") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        return data
                except Exception:
                    pass
        return {}

    def _resolve_layout(self, instance_id: str) -> Optional[dict]:
        from core.instance_layout import resolve_steam_game_layout
        install_subfolder = str(self._plugin.get("install_subfolder") or "")
        if not install_subfolder:
            return None

        plugin_defaults = self._load_defaults()
        cluster_cfg = self._load_cluster_config()

        defaults = {**plugin_defaults}
        for key in ("steamcmd_root", "gameservers_root", "cluster_name"):
            val = cluster_cfg.get(key)
            if val:
                defaults[key] = val

        inst = self._load_instance_config(instance_id) or {}
        try:
            layout = resolve_steam_game_layout(
                defaults,
                inst,
                instance_id,
                default_install_folder=install_subfolder,
                default_cluster_name=install_subfolder.lower(),
                default_legacy_server_subdir="server",
            )
            # inject cluster-rooted paths
            if not layout.get("install_root") and self._cluster_root:
                layout["install_root"] = os.path.join(
                    self._cluster_root, "gameservers", install_subfolder
                )
            return layout
        except Exception:
            return None

    def _resolve_master_layout(self) -> Optional[dict]:
        from core.instance_layout import resolve_steam_game_master_layout

        install_subfolder = str(self._plugin.get("install_subfolder") or "")
        plugin_name = str(self._plugin.get("name") or "")
        if not install_subfolder or not plugin_name:
            return None

        plugin_defaults = self._load_defaults()
        cluster_cfg = self._load_cluster_config()

        defaults = {**plugin_defaults}
        for key in ("steamcmd_root", "gameservers_root", "cluster_name"):
            val = cluster_cfg.get(key)
            if val:
                defaults[key] = val

        try:
            return resolve_steam_game_master_layout(
                defaults,
                plugin_name=plugin_name,
                default_install_folder=install_subfolder,
            )
        except Exception:
            return None

    def _create_dirs(self, layout: dict) -> dict:
        created: Dict[str, str] = {}
        for key in ("cluster_dir", "map_dir", "server_dir", "logs_dir", "tmp_dir"):
            p = layout.get(key)
            if not p:
                continue
            os.makedirs(str(p), exist_ok=True)
            created[key] = str(p)
        return created

    def _resolve_steamcmd_exe(self, layout: dict) -> Optional[str]:
        steamcmd_dir = str(layout.get("steamcmd_dir") or "")
        if not steamcmd_dir:
            return None
        p = os.path.join(steamcmd_dir, "steamcmd.exe")
        if os.path.exists(p) and os.path.isfile(p):
            return p
        return None

    def _load_defaults(self) -> dict:
        plugin_defaults: dict = dict(self._plugin or {})
        for filename in ("plugin_defaults.json", "plugin_config.json"):
            path = os.path.join(self._plugin_dir, filename)
            if os.path.exists(path):
                try:
                    import json
                    with open(path, "r", encoding="utf-8-sig") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        plugin_defaults = data
                        break
                except Exception:
                    pass
        cluster_cfg = self._load_cluster_config()
        for key in ("steamcmd_root", "gameservers_root", "cluster_name"):
            val = cluster_cfg.get(key)
            if val and key not in plugin_defaults:
                plugin_defaults[key] = val
        return plugin_defaults

    def _candidate_discovery_roots(self) -> list[str]:
        defaults = self._load_defaults()
        gameservers_root = str(defaults.get("gameservers_root") or "").strip()
        install_root = str(defaults.get("install_root") or "").strip()
        install_subfolder = str(self._plugin.get("install_subfolder") or "").strip()

        roots: list[str] = []

        def _add_root(path: str) -> None:
            candidate = str(path or "").strip()
            if not candidate:
                return
            normalized = os.path.normcase(os.path.abspath(candidate))
            if normalized in {os.path.normcase(os.path.abspath(item)) for item in roots}:
                return
            roots.append(candidate)

        if install_root:
            if os.path.isabs(install_root):
                _add_root(install_root)
            elif gameservers_root:
                _add_root(os.path.join(gameservers_root, install_root))
        if gameservers_root and install_subfolder:
            _add_root(os.path.join(gameservers_root, install_subfolder))
        if gameservers_root:
            _add_root(gameservers_root)
        return roots

    def _install_target(self, payload: dict) -> str:
        target = str(payload.get("install_target") or "").strip().lower()
        if target == "master" or payload.get("use_master_install") is True:
            return "master"
        return "instance"

    def _is_master_install_path(self, install_path: str) -> bool:
        master_layout = self._resolve_master_layout()
        master_root = str((master_layout or {}).get("install_root") or "").strip()
        candidate_root = str(install_path or "").strip()
        if not master_root or not candidate_root:
            return False
        try:
            return os.path.normcase(os.path.abspath(candidate_root)) == os.path.normcase(os.path.abspath(master_root))
        except Exception:
            return False

    def _iter_discovery_install_paths(self, root: str) -> list[str]:
        entries = []
        try:
            entries.append(str(root))
            for name in os.listdir(root):
                candidate = os.path.join(root, name)
                if os.path.isdir(candidate):
                    entries.append(candidate)
        except Exception:
            return []

        discovered = []
        for candidate in entries:
            if self._is_master_install_path(candidate):
                continue
            exe_path = self._discovery_executable_path(candidate)
            if exe_path and os.path.isfile(exe_path):
                discovered.append(candidate)
        return discovered

    def _discovery_executable_path(self, install_path: str) -> Optional[str]:
        server_dir = str(install_path or "")
        exe_rel = str(self._plugin.get("executable") or "")
        if not server_dir or not exe_rel:
            return None
        return os.path.join(server_dir, exe_rel.replace("/", os.sep).replace("\\", os.sep))

    def _build_discovery_candidate(self, install_path: str) -> Optional[dict]:
        install_root = str(install_path or "").strip()
        if not install_root:
            return None
        detected_map = self._detect_candidate_map(install_root)
        exe_path = self._discovery_executable_path(install_root) or ""
        managed_match, managed_instance_id = self._match_managed_install_root(install_root)
        ini_fields = self._detect_candidate_ini_fields(install_root)
        ports = self._detect_candidate_ports(install_root, ini_fields=ini_fields)
        return {
            "install_path": install_root,
            "detected_map": detected_map,
            "executable_path": exe_path,
            "ports": ports,
            "ini_fields": ini_fields,
            "managed_match": bool(managed_match),
            "managed_instance_id": str(managed_instance_id or ""),
        }

    def _read_ini_settings_values(self, install_root: str) -> dict[tuple[str, str], str]:
        ini_cfg = self._plugin.get("ini_settings")
        if not isinstance(ini_cfg, dict):
            return {}
        ini_rel = str(ini_cfg.get("file") or "").strip()
        fields_map = ini_cfg.get("fields") or {}
        if not ini_rel or not isinstance(fields_map, dict):
            return {}

        ini_path = os.path.join(str(install_root), ini_rel.replace("/", os.sep).replace("\\", os.sep))
        if not os.path.isfile(ini_path):
            return {}

        try:
            with open(ini_path, "r", encoding="utf-8", errors="replace") as handle:
                lines = handle.readlines()
        except Exception:
            return {}

        section = ""
        values: dict[tuple[str, str], str] = {}
        for raw_line in lines:
            text = str(raw_line).strip()
            if not text or text.startswith(";") or text.startswith("#"):
                continue
            if text.startswith("[") and text.endswith("]"):
                section = text[1:-1].strip()
                continue
            if "=" not in text:
                continue
            key, value = text.split("=", 1)
            values[(section.lower(), key.strip().lower())] = value.strip()
        return values

    def _coerce_discovered_ini_value(self, field_name: str, raw_value: str):
        server_settings_raw = self._plugin.get("server_settings")
        app_settings_raw = self._plugin.get("app_settings")
        server_settings = server_settings_raw if isinstance(server_settings_raw, dict) else {}
        app_settings = app_settings_raw if isinstance(app_settings_raw, dict) else {}
        field_meta = None
        server_field = server_settings.get(field_name)
        app_field = app_settings.get(field_name)
        if isinstance(server_field, dict):
            field_meta = server_field
        elif isinstance(app_field, dict):
            field_meta = app_field
        field_type = str((field_meta or {}).get("type") or "").strip().lower()
        text = str(raw_value or "").strip()
        if not text:
            return None
        if field_type == "int":
            try:
                return int(text)
            except Exception:
                return None
        if field_type == "bool":
            lowered = text.lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True
            if lowered in {"false", "0", "no", "off"}:
                return False
            return None
        if field_type == "list":
            values = [item.strip() for item in text.split(",") if item.strip()]
            return values
        return text

    def _detect_candidate_ini_fields(self, install_root: str) -> dict:
        ini_cfg = self._plugin.get("ini_settings")
        if not isinstance(ini_cfg, dict):
            return {}
        fields_map = ini_cfg.get("fields") or {}
        if not isinstance(fields_map, dict):
            return {}

        values = self._read_ini_settings_values(install_root)
        if not values:
            return {}

        discovered = {}
        for field_name, mapping in fields_map.items():
            if not isinstance(mapping, dict):
                continue
            section_name = str(mapping.get("section") or "").strip().lower()
            key_names = mapping.get("keys")
            if isinstance(key_names, list):
                lookup_keys = [str(item).strip().lower() for item in key_names if str(item).strip()]
            else:
                key_name = str(mapping.get("key") or "").strip().lower()
                lookup_keys = [key_name] if key_name else []
            if not section_name or not lookup_keys:
                continue
            raw_value = None
            for key_name in lookup_keys:
                raw_value = values.get((section_name, key_name))
                if raw_value is not None:
                    break
            if raw_value is None:
                continue
            coerced = self._coerce_discovered_ini_value(str(field_name), raw_value)
            if coerced is not None:
                discovered[str(field_name)] = coerced
        return discovered

    def _detect_candidate_ports(self, install_root: str, *, ini_fields: Optional[dict] = None) -> list[dict]:
        ports: list[dict] = []
        ini_fields = ini_fields if isinstance(ini_fields, dict) else self._detect_candidate_ini_fields(install_root)
        for spec in list(self._plugin.get("required_ports") or []):
            if not isinstance(spec, dict):
                continue
            name = str(spec.get("name") or "").strip()
            proto = str(spec.get("proto") or "").strip()
            entry: Dict[str, Any] = {"name": name, "proto": proto}
            port_value = ini_fields.get(f"{name}_port")
            if isinstance(port_value, int) and 1 <= int(port_value) <= 65535:
                entry["port"] = int(port_value)
            ports.append(entry)
        return ports

    def _detect_candidate_map(self, install_root: str) -> str:
        detected = self._detect_map_from_savedarks(install_root)
        if detected:
            return detected
        return self._detect_map_from_install_path(install_root)

    def _normalize_detected_map_name(self, raw_name: str) -> str:
        text = str(raw_name or "").strip()
        if not text:
            return ""

        known_maps = self._plugin.get("maps")
        if not isinstance(known_maps, dict):
            known_maps = {}
        lowered = text.lower()
        for raw_known in known_maps.keys():
            known_name = str(raw_known or "").strip()
            if known_name and known_name.lower() == lowered:
                return known_name

        if lowered.endswith("_wp"):
            stem = text[:-3]
            if stem:
                return f"{stem}_WP"
            return text

        return f"{text}_WP"

    def _detect_map_from_savedarks(self, install_root: str) -> str:
        savedarks_root = os.path.join(
            str(install_root),
            "ShooterGame",
            "Saved",
            "SavedArks",
        )
        if not os.path.isdir(savedarks_root):
            return ""

        try:
            map_dirs = sorted(
                [
                    entry
                    for entry in os.listdir(savedarks_root)
                    if os.path.isdir(os.path.join(savedarks_root, entry))
                ]
            )
        except Exception:
            return ""

        if not map_dirs:
            return ""

        known_maps = self._plugin.get("maps")
        if not isinstance(known_maps, dict):
            known_maps = {}
        normalized_known = {
            self._normalize_detected_map_name(str(raw_name or "")).lower(): str(raw_name or "").strip()
            for raw_name in known_maps.keys()
            if str(raw_name or "").strip()
        }

        for entry in map_dirs:
            normalized = self._normalize_detected_map_name(entry)
            known = normalized_known.get(normalized.lower())
            if known:
                return known

        return self._normalize_detected_map_name(map_dirs[0])

    def _detect_map_from_install_path(self, install_path: str) -> str:
        folder_name = os.path.basename(str(install_path or "")).strip()
        lowered = folder_name.lower()
        known_maps = self._plugin.get("maps")
        if not isinstance(known_maps, dict):
            known_maps = {}
        for raw_name in known_maps.keys():
            map_name = str(raw_name or "").strip()
            lowered_map = map_name.lower()
            if lowered == lowered_map or lowered.endswith(lowered_map):
                return map_name
        marker = "_wp"
        idx = lowered.rfind(marker)
        if idx >= 0:
            start = lowered.rfind("_", 0, idx)
            if start >= 0:
                return folder_name[start + 1:]
            return folder_name
        return folder_name

    def _match_managed_install_root(self, install_path: str) -> tuple[bool, str]:
        from core.instance_layout import get_instances_root
        plugin_name = str(self._plugin_key or "").strip()
        managed_root = os.path.normcase(os.path.abspath(str(install_path or "")))
        instances_root = str(get_instances_root(str(self._cluster_root), plugin_name))
        if not os.path.isdir(instances_root):
            return False, ""

        for instance_id in os.listdir(instances_root):
            config = self._load_instance_config(str(instance_id)) or {}
            configured_root = str(config.get("install_root") or "").strip()
            if not configured_root:
                continue
            if os.path.normcase(os.path.abspath(configured_root)) == managed_root:
                return True, str(instance_id)
        return False, ""

    def _load_instance_config(self, instance_id: str) -> Optional[dict]:
        if not instance_id:
            return None
        from core.plugin_config import resolve_instance_config_path
        import json
        plugin_name = str(self._plugin_key or "").strip()
        candidates = []
        if self._cluster_root and plugin_name:
            candidates.append(str(resolve_instance_config_path(str(self._cluster_root), plugin_name, instance_id)))
            candidates.append(
                os.path.join(
                    str(self._cluster_root),
                    "instances",
                    plugin_name,
                    instance_id,
                    "config",
                    "instance_config.json",
                )
            )
            candidates.append(
                os.path.join(
                    str(self._cluster_root),
                    "instances",
                    plugin_name,
                    instance_id,
                    "config",
                    "plugin_instance_config.json",
                )
            )
        # Fallback: look directly in plugin_dir
        candidates.append(os.path.join(self._plugin_dir, "instances", instance_id, "config", "instance_config.json"))
        candidates.append(os.path.join(self._plugin_dir, "instances", instance_id, "config", "plugin_instance_config.json"))
        for path in candidates:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8-sig") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        return data
                except Exception:
                    pass
        return None

    def _write_ini_settings(self, instance_id: str, server_dir: str, *, field_names: Optional[list[str]] = None) -> list:
        warnings: list[str] = []
        ini_cfg = self._plugin.get("ini_settings")
        if not ini_cfg or not isinstance(ini_cfg, dict):
            return warnings

        ini_file_rel = ini_cfg.get("file", "")
        fields_map = ini_cfg.get("fields") or {}
        if not ini_file_rel or not fields_map:
            return warnings

        ini_path = os.path.join(server_dir, ini_file_rel.replace("/", os.sep).replace("\\", os.sep))

        defaults = self._load_defaults()
        inst = self._load_instance_config(instance_id) or {}
        active_mods = self._coerce_csv_list(self._effective_active_mods(defaults, inst))
        passive_mods = self._coerce_csv_list(self._effective_passive_mods(defaults, inst))
        session_name = self._effective_server_name(defaults, inst)
        max_players = self._effective_max_players(defaults, inst)

        expected: Dict[str, Dict[str, str]] = {}
        allowed_fields = self._normalize_ini_field_names(field_names)
        for field_name, mapping in fields_map.items():
            if allowed_fields is not None and str(field_name) not in allowed_fields:
                continue
            section = mapping.get("section", "")
            key_names = mapping.get("keys")
            if isinstance(key_names, list):
                keys = [str(item).strip() for item in key_names if str(item).strip()]
            else:
                key = str(mapping.get("key") or "").strip()
                keys = [key] if key else []
            if not section or not keys:
                continue
            value = self._effective_ini_field_value(field_name, defaults, inst)
            if value is None:
                continue
            if field_name == "mods":
                value = ",".join(active_mods)
            elif field_name == "passive_mods":
                value = ",".join(passive_mods)
            elif field_name == "server_name":
                value = session_name
            elif field_name == "max_players":
                value = max_players
            if value is None:
                continue
            for key_name in keys:
                expected.setdefault(str(section), {})[str(key_name)] = str(value)

        if not expected:
            return warnings

        try:
            self._patch_ini(ini_path, expected)
        except Exception as exc:
            warnings.append(f"INI write warning: {exc}")
        return warnings

    def _normalize_ini_field_names(self, field_names: Optional[list[str]]) -> Optional[set[str]]:
        if field_names is None:
            return None
        out = {str(item).strip() for item in list(field_names or []) if str(item).strip()}
        if "display_name" in out:
            out.add("server_name")
        return out

    def _patch_ini(self, path: str, expected: Dict[str, Dict[str, str]]) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        text = ""
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8-sig") as f:
                text = f.read()
        lines = text.splitlines()

        def section_bounds(name: str):
            start = None
            end = len(lines)
            for idx, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("[") and stripped.endswith("]"):
                    sname = stripped[1:-1].strip()
                    if start is None and sname == name:
                        start = idx
                        continue
                    if start is not None:
                        end = idx
                        break
            return start, end

        for section_name, values in expected.items():
            start, end = section_bounds(section_name)
            if start is None:
                if lines and lines[-1].strip():
                    lines.append("")
                lines.append(f"[{section_name}]")
                for k, v in values.items():
                    lines.append(f"{k}={v}")
                continue

            present = {}
            for idx in range(start + 1, end):
                line = lines[idx]
                stripped = line.strip()
                if not stripped or stripped.startswith(";") or stripped.startswith("#") or "=" not in line:
                    continue
                lhs, rhs = line.split("=", 1)
                k = lhs.strip()
                if k in values:
                    present[k] = idx
                    if rhs.strip() != str(values[k]):
                        lines[idx] = f"{k}={values[k]}"

            insertion_index = end
            for k, v in values.items():
                if k not in present:
                    lines.insert(insertion_index, f"{k}={v}")
                    insertion_index += 1

        self._write_text_file(path, "\n".join(lines) + ("\n" if lines else ""))

    def _effective_ini_field_value(self, field_name: str, defaults: dict, inst: dict):
        if field_name == "mods":
            values = self._coerce_csv_list(self._effective_active_mods(defaults, inst))
            return ",".join(values) if values else None
        if field_name == "passive_mods":
            values = self._coerce_csv_list(self._effective_passive_mods(defaults, inst))
            return ",".join(values) if values else None
        if field_name == "server_name":
            return self._effective_server_name(defaults, inst)
        if field_name == "max_players":
            return self._effective_max_players(defaults, inst)
        if field_name == "pve":
            return self._effective_pve(defaults, inst)

        value = inst.get(field_name)
        if value is None:
            value = defaults.get(field_name)
        if value is None:
            value = (self._plugin.get("server_settings") or {}).get(field_name, {}).get("value")
        if value is None:
            value = (self._plugin.get("app_settings") or {}).get(field_name, {}).get("value")
        return value

    def _coerce_csv_list(self, value) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value or "").strip()
        if not text:
            return []
        return [item.strip() for item in text.split(",") if item.strip()]

    def _effective_active_mods(self, defaults: dict, inst: dict) -> list[str]:
        from core.launcher import compute_effective_active_mods
        return compute_effective_active_mods(defaults, inst)

    def _effective_passive_mods(self, defaults: dict, inst: dict) -> list[str]:
        from core.launcher import compute_effective_passive_mods
        return compute_effective_passive_mods(defaults, inst)

    def _effective_max_players(self, defaults: dict, inst: dict):
        value = inst.get("max_players")
        if value is None:
            value = defaults.get("max_players")
        if value is None:
            value = (self._plugin.get("server_settings") or {}).get("max_players", {}).get("value")
        if value is None:
            value = (self._plugin.get("app_settings") or {}).get("max_players", {}).get("value")
        if value is None:
            return None
        try:
            out = int(value)
        except Exception:
            return None
        return out if 1 <= out <= 65535 else None

    def _effective_admin_password(self, defaults: dict, inst: dict) -> str:
        value = inst.get("admin_password")
        if value is None:
            value = defaults.get("admin_password")
        return str(value or "").strip()

    def _effective_rcon_enabled(self, defaults: dict, inst: dict) -> bool:
        value = inst.get("rcon_enabled")
        if value is None:
            value = defaults.get("rcon_enabled")
        if value is None:
            value = (self._plugin.get("server_settings") or {}).get("rcon_enabled", {}).get("value")
        if value is None:
            value = (self._plugin.get("app_settings") or {}).get("rcon_enabled", {}).get("value")
        return bool(value)

    def _effective_pve(self, defaults: dict, inst: dict) -> bool:
        value = inst.get("pve")
        if value is None:
            value = defaults.get("pve")
        if value is None:
            value = (self._plugin.get("app_settings") or {}).get("pve", {}).get("value")
        return bool(value)

    def _friendly_map_name(self, value: object) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        known_maps = self._plugin.get("maps")
        if not isinstance(known_maps, dict):
            known_maps = {}
        lowered = raw.lower()
        for known_key, entry in known_maps.items():
            if str(known_key or "").strip().lower() != lowered:
                continue
            if isinstance(entry, dict):
                display_name = str(entry.get("display_name") or "").strip()
                if display_name:
                    return display_name
        text = raw[:-3] if raw.lower().endswith("_wp") else raw
        text = text.replace("_", " ").strip()
        return " ".join(part[:1].upper() + part[1:] for part in text.split(" ") if part)

    def _effective_server_name(self, defaults: dict, inst: dict) -> str:
        explicit = str(inst.get("server_name") or defaults.get("server_name") or "").strip()
        if explicit:
            return explicit
        prefix = str(defaults.get("display_name") or "").strip()
        friendly_map = self._friendly_map_name(inst.get("map") or defaults.get("map") or "")
        if prefix and friendly_map:
            return f"{prefix}{friendly_map}"
        if friendly_map:
            return friendly_map
        return str(self._plugin.get("display_name") or "Server")

    def _derive_cluster_dir_override(self, defaults: dict) -> str:
        cluster_cfg = self._load_cluster_config()
        gameservers_root = str(cluster_cfg.get("gameservers_root") or defaults.get("gameservers_root") or "").strip()
        install_root = str(defaults.get("install_root") or "").strip()
        if not gameservers_root or not install_root:
            return ""
        path = os.path.join(gameservers_root, install_root, "Cluster")
        if "/" in gameservers_root and "\\" not in gameservers_root:
            return path.replace("\\", "/")
        return path

    # ------------------------------------------------------------------
    # I/O helpers (thin wrappers passed to core functions)
    # ------------------------------------------------------------------

    @staticmethod
    def _steamcmd_native_console_log_path(steamcmd_exe: str) -> str:
        root = os.path.dirname(os.path.abspath(str(steamcmd_exe or ""))) if steamcmd_exe else ""
        if not root:
            return ""
        return os.path.join(root, "logs", "console_log.txt")

    @staticmethod
    def _file_size_or_zero(path: str) -> int:
        try:
            return int(os.path.getsize(path))
        except Exception:
            return 0

    @staticmethod
    def _write_text_file(path: str, content: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def _write_json_file(path: str, data: dict) -> None:
        import json
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    @staticmethod
    def _format_cmd_for_log(cmd) -> str:
        if isinstance(cmd, list):
            return " ".join(str(x) for x in cmd)
        return str(cmd)

    @staticmethod
    def _tail_file_lines(path: str, n: int):
        if not os.path.exists(path):
            return False, []
        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
                lines = f.readlines()
            return True, [line.rstrip("\n") for line in lines[-n:]]
        except Exception:
            return False, []
