############################################################
# SECTION: Admin API (Local In-Process Surface)
# Purpose:
#     Stateless facade over Orchestrator.
# Lifecycle Ownership:
#     None (Delegation Only)
# Phase:
#     CG-ADMIN-API-1
# Constraints:
#     - No network
#     - No threads
#     - No async
#     - No lifecycle legality
#     - No state mutation
#     - Orchestrator remains sole authority
############################################################

def _orch_method(orchestrator, name):
    instance_dict = getattr(orchestrator, "__dict__", {})
    candidate = instance_dict.get(name)
    if callable(candidate):
        return candidate
    owner_attr = getattr(type(orchestrator), name, None)
    if callable(owner_attr):
        return lambda *args, **kwargs: owner_attr(orchestrator, *args, **kwargs)
    return None


class AdminAPI:
    _INI_SYNC_FIELDS = {"mods", "passive_mods", "max_players", "game_port", "rcon_port", "rcon_enabled", "admin_password", "server_name", "display_name"}
    _PLUGIN_PROPAGATED_INSTANCE_FIELDS = {"rcon_enabled", "admin_password", "pve"}

    ############################################################
    # SECTION: Initialization
    ############################################################
    def __init__(self, orchestrator):
        self._orchestrator = orchestrator

    ############################################################
    # SECTION: Construction (Pure Wiring)
    # Purpose:
    #   Deterministic in-process construction for CLI.
    # Constraints:
    #   - No semantics
    #   - No threads/async/timers
    ############################################################
    @classmethod
    def build_default(cls, plugin_dir="plugins", state_file=None, cluster_root=None):
        from pathlib import Path
        from core.plugin_registry import PluginRegistry
        from core.state_manager import StateManager
        from core.orchestrator import Orchestrator

        Path(plugin_dir).mkdir(parents=True, exist_ok=True)

        registry = PluginRegistry(plugin_dir=plugin_dir, cluster_root=cluster_root)
        state = StateManager(state_file=state_file)

        # Pure wiring: pass cluster_root into Orchestrator for deterministic filesystem paths
        orchestrator = Orchestrator(registry, state, cluster_root=cluster_root)

        registry.load_all()
        return cls(orchestrator)

    ############################################################
    # SECTION: Best-Effort Cleanup (Delegation Only)
    # Purpose:
    #     Shutdown plugin processes started by load_all()
    # Constraints:
    #     - Delegation only
    #     - Best-effort (ignore failures)
    ############################################################
    def shutdown_all_plugins(self):
        for plugin_name in self.get_all_plugins():
            try:
                self._orchestrator.shutdown_plugin(plugin_name)
            except Exception:
                pass

    def close(self):
        self.shutdown_all_plugins()

    ############################################################
    # SECTION: Read-Only Snapshot Methods
    ############################################################
    def _runtime_info(self, plugin_name, instance_id):
        try:
            resp = self.read_cached_runtime_summary(plugin_name, instance_id)
        except Exception:
            return {"running": False, "ready": False, "response": None}

        running = False
        ready = False
        if isinstance(resp, dict) and resp.get("status") == "success":
            data = resp.get("data")
            if isinstance(data, dict):
                running = bool(data.get("running"))
                ready = bool(data.get("ready"))

        return {"running": running, "ready": ready, "response": resp}

    def read_cached_runtime_summary(self, plugin_name, instance_id):
        fn = getattr(self._orchestrator, "read_cached_runtime_summary", None)
        if callable(fn):
            return fn(str(plugin_name), str(instance_id))
        return {
            "status": "success",
            "data": {
                "ok": True,
                "display_name": "",
                "running": False,
                "ready": False,
                "pid": None,
                "version": {"installed": None, "running": None},
                "warnings": [],
                "errors": [],
            },
        }

    def refresh_runtime_summary(self, plugin_name, instance_id):
        fn = getattr(self._orchestrator, "refresh_runtime_summary", None)
        if callable(fn):
            return fn(str(plugin_name), str(instance_id))
        return self.read_cached_runtime_summary(plugin_name, instance_id)

    def read_cached_instance_status(self, plugin_name, instance_id):
        # Authoritative lifecycle state (read-only) when available.
        # For legacy tests/stubs that do not implement get_instance_state, fall back deterministically.
        state = "STOPPED"

        get_state = getattr(self._orchestrator, "get_instance_state", None)
        if callable(get_state):
            state = get_state(plugin_name, instance_id)

        try:
            if state == self._orchestrator._state_manager.DISABLED:
                state_for_display = self._orchestrator._state_manager.STOPPED
            else:
                state_for_display = state
        except Exception:
            state_for_display = state

        install_status = self._orchestrator.get_instance_install_status(plugin_name, instance_id)
        runtime = self._runtime_info(plugin_name, instance_id)
        runtime_running = bool(runtime.get("running"))
        runtime_ready = bool(runtime.get("ready"))

        last_action = None
        get_last_action = getattr(self._orchestrator, "get_instance_last_action", None)
        if callable(get_last_action):
            try:
                value = get_last_action(plugin_name, instance_id)
                last_action = None if value is None else str(value)
            except Exception:
                last_action = None

        if not runtime_running:
            if str(state_for_display).upper() in {"STARTING", "STOPPING", "RESTARTING"}:
                effective_state = str(state_for_display).upper()
            else:
                effective_state = "STOPPED"
        elif str(last_action) == "stop":
            effective_state = "STOPPING"
        elif str(last_action) == "restart" and not runtime_ready:
            effective_state = "RESTARTING"
        elif runtime_ready:
            effective_state = "STARTED"
        elif str(last_action) == "start":
            effective_state = "STARTING"
        else:
            effective_state = "STARTING"

        return {
            "plugin_name": plugin_name,
            "instance_id": instance_id,
            "state": effective_state,
            "last_action": last_action,
            "core_state": state_for_display,
            "effective_state": effective_state,
            "runtime_running": runtime_running,
            "runtime_ready": runtime_ready,
            "disabled": self._orchestrator.get_instance_disabled_state(plugin_name, instance_id),
            "crash_total_count": self._orchestrator.get_crash_total_count(plugin_name, instance_id),
            "crash_stability_count": self._orchestrator.get_crash_stability_count(plugin_name, instance_id),
            "effective_threshold": self._orchestrator.get_effective_threshold(plugin_name, instance_id),
            "crash_restart_paused": self._orchestrator.is_crash_restart_paused(plugin_name, instance_id),
            "install_status": install_status,
        }

    def refresh_instance_status(self, plugin_name, instance_id):
        reconcile = getattr(self._orchestrator, "reconcile_stop_progress", None)
        if callable(reconcile):
            try:
                reconcile(plugin_name, instance_id)
            except Exception:
                pass
        return self.read_cached_instance_status(plugin_name, instance_id)

    def get_instance_status(self, plugin_name, instance_id):
        return self.read_cached_instance_status(plugin_name, instance_id)

    def get_dashboard_status_snapshot(self):
        grouped = {}
        for p in self.get_all_plugins():
            plugin = str(p)
            instances = []
            err = None

            try:
                resp = self.list_instances(plugin)
                if isinstance(resp, dict) and resp.get("status") == "success":
                    data = resp.get("data")
                    vals = data.get("instances") if isinstance(data, dict) else []
                    if isinstance(vals, list):
                        for item in vals:
                            if isinstance(item, str):
                                instances.append(item)
                            elif isinstance(item, dict) and item.get("instance_id") is not None:
                                instances.append(str(item.get("instance_id")))
                else:
                    err = str(resp.get("message") or f"list_instances status={resp.get('status')}") if isinstance(resp, dict) else "list_instances failed"
            except Exception as e:
                err = str(e)

            statuses = []
            for iid in instances:
                try:
                    statuses.append(self.read_cached_instance_status(plugin, iid))
                except Exception as e:
                    statuses.append({"plugin_name": plugin, "instance_id": iid, "error": str(e)})

            grouped[plugin] = {"instance_ids": instances, "status": statuses, "error": err}

        return {"status": "success", "data": {"plugins": grouped}}

    def get_all_plugins(self):
        return list(self._orchestrator.list_plugins())

    def reload_plugins(self):
        self._orchestrator.load_plugins()
        return {"status": "success", "data": {"plugins": self.get_all_plugins()}}

    def get_dependency_report(self, plugin_name=None):
        data = self._orchestrator.get_plugin_dependency_report(plugin_name=plugin_name)
        return {"status": "success", "data": data}

    def read_cached_plugin_readiness_report(self, plugin_name):
        fn = getattr(self._orchestrator, "read_cached_plugin_readiness_report", None)
        if not callable(fn):
            fallback = getattr(self._orchestrator, "get_plugin_readiness_report", None)
            if callable(fallback):
                return {"status": "success", "data": fallback(str(plugin_name))}
            return {"status": "success", "data": {"plugin_name": str(plugin_name), "status": "installed", "results": []}}
        return {"status": "success", "data": fn(str(plugin_name))}

    def refresh_plugin_readiness_report(self, plugin_name):
        fn = getattr(self._orchestrator, "refresh_plugin_readiness_report", None)
        if not callable(fn):
            return self.read_cached_plugin_readiness_report(plugin_name)
        return {"status": "success", "data": fn(str(plugin_name))}

    def get_plugin_readiness_report(self, plugin_name):
        # Compatibility cached-read alias for GUI/CLI callers that still use a
        # getter-style name.
        return self.read_cached_plugin_readiness_report(plugin_name)

    def read_cached_app_setup_report(self):
        fn = getattr(self._orchestrator, "read_cached_app_setup_report", None)
        if not callable(fn):
            fallback = getattr(self._orchestrator, "get_app_setup_report", None)
            if callable(fallback):
                return {"status": "success", "data": fallback()}
            return {"status": "success", "data": {"status": "missing", "results": []}}
        return {"status": "success", "data": fn()}

    def refresh_app_setup_report(self):
        fn = getattr(self._orchestrator, "refresh_app_setup_report", None)
        if not callable(fn):
            return self.read_cached_app_setup_report()
        return {"status": "success", "data": fn()}

    def get_app_setup_report(self):
        # Compatibility cached-read alias for GUI/CLI callers that still use a
        # getter-style name.
        return self.read_cached_app_setup_report()

    def install_steamcmd(self):
        if not hasattr(self._orchestrator, "install_steamcmd"):
            return {"status": "error", "message": "Orchestrator missing install_steamcmd()."}
        return self._orchestrator.install_steamcmd()

    def activate_plugin_source(self, source_dir):
        return self._orchestrator.activate_plugin_source(source_dir)
    def list_instances(self, plugin_name):
        """List instances for a plugin by scanning the filesystem (deterministic, game-agnostic).

        Source of truth:
          <install_root_dir>/<plugin_name>/<instance_id>/instance.json

        Legacy fallback:
          <cluster_root>/plugins/<plugin_name>/instances/<instance_id>/instance.json

        Returns canonical envelope:
          {"status":"success","data":{"plugin":<name>,"instances":[...]}}
        """
        from core.instance_layout import get_instances_root

        cluster_root = getattr(self._orchestrator, "_cluster_root", None)
        if not cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}

        base = get_instances_root(str(cluster_root), str(plugin_name))
        if not base.exists() or not base.is_dir():
            return {"status": "success", "data": {"plugin": str(plugin_name), "instances": []}}

        instances = []
        try:
            for p in sorted([x for x in base.iterdir() if x.is_dir()], key=lambda x: x.name):
                meta = p / "instance.json"
                if meta.exists() and meta.is_file():
                    instances.append(p.name)
        except Exception as e:
            return {"status": "error", "message": str(e)}

        return {"status": "success", "data": {"plugin": str(plugin_name), "instances": instances}}

    def get_scheduler_status(self):
        return {
            "maintenance_active": self._orchestrator.is_maintenance_active(),
            "maintenance_paused": self._orchestrator.is_maintenance_paused(),
            "maintenance_failed": self._orchestrator.is_maintenance_failed(),
            "current_plugin": self._orchestrator.get_current_maintenance_plugin(),
            "failed_plugin_count": self._orchestrator.get_failed_plugin_count(),
            "escalation_threshold": self._orchestrator.get_escalation_threshold(),
            "next_window_time": self._orchestrator.get_next_window_time(),
        }

    def tick_scheduled_tasks(self, current_datetime=None):
        fn = getattr(self._orchestrator, "tick_scheduled_tasks", None)
        if not callable(fn):
            return {"status": "success", "data": {"update_checks": [], "scheduled_restarts": []}}
        return {"status": "success", "data": fn(current_datetime=current_datetime)}

    def get_plugin_schedule_status(self, plugin_name, current_datetime=None):
        fn = getattr(self._orchestrator, "get_plugin_schedule_status", None)
        if not callable(fn):
            return {"status": "success", "data": {"plugin_name": str(plugin_name)}}
        return {"status": "success", "data": fn(str(plugin_name), current_datetime=current_datetime)}

    def poll_events(self):
        fn = getattr(self._orchestrator, "poll_events", None)
        if not callable(fn):
            return {"status": "success", "data": {"events": []}}
        return {"status": "success", "data": {"events": list(fn() or [])}}

    ############################################################
    # SECTION: Observability (Read-Only)
    ############################################################
    def get_events_all(self):
        return self._orchestrator.get_events()

    def get_events_last(self, n):
        n = int(n)
        events = self._orchestrator.get_events()
        if n <= 0:
            return []
        return events[-n:]

    def _cluster_config_path(self):
        from pathlib import Path

        cluster_root = getattr(self._orchestrator, "_cluster_root", None)
        if not cluster_root:
            return None

        root = Path(cluster_root)
        candidates = [
            root / "cluster_config.json",
            root / "config" / "cluster_config.json",
        ]

        for p in candidates:
            if p.exists() and p.is_file():
                return p

        return candidates[0]

    def _default_cluster_config(self):
        from core.config_models import ClusterConfig
        from pathlib import Path

        cluster_root = getattr(self._orchestrator, "_cluster_root", None)
        root = Path(cluster_root) if cluster_root else Path(".")

        return ClusterConfig(
            install_root_dir=str(root / "instances"),
            cluster_name="arkSA",
            cluster_id=None,
            base_game_port=30000,
            base_rcon_port=31000,
            backup_dir=str(root / "backups"),
            instances=[],
            gameservers_root="",
            steamcmd_root="",
        ).normalized()

    def get_cluster_config_fields(self, fields=None):
        from core.config_io import load_cluster_config

        path = self._cluster_config_path()
        if path is None:
            return {"status": "error", "message": "Cluster root not configured"}

        allowed = {"gameservers_root", "cluster_name", "steamcmd_root"}

        requested = None
        if fields is not None:
            requested = [str(x) for x in fields]
            unknown = sorted([k for k in requested if k not in allowed])
            if unknown:
                return {"status": "error", "message": f"Unknown cluster config fields: {', '.join(unknown)}"}

        try:
            if path.exists():
                cfg = load_cluster_config(path)
            else:
                cfg = self._default_cluster_config()
        except Exception as e:
            return {"status": "error", "message": f"Failed to load cluster config: {e}"}

        current = {
            "gameservers_root": str(cfg.gameservers_root),
            "cluster_name": str(cfg.cluster_name),
            "steamcmd_root": str(getattr(cfg, "steamcmd_root", "") or ""),
        }

        if requested is None:
            selected = dict(current)
        else:
            selected = {k: current.get(k) for k in requested}

        return {"status": "success", "data": {"fields": selected, "path": str(path)}}

    def set_cluster_config_fields(self, fields):
        from dataclasses import replace
        from core.config_io import load_cluster_config, save_cluster_config

        if not isinstance(fields, dict):
            return {"status": "error", "message": "fields must be a dict"}

        path = self._cluster_config_path()
        if path is None:
            return {"status": "error", "message": "Cluster root not configured"}

        allowed = {"gameservers_root", "cluster_name", "steamcmd_root"}
        unknown = sorted([str(k) for k in fields.keys() if str(k) not in allowed])
        if unknown:
            return {"status": "error", "message": f"Unknown cluster config fields: {', '.join(unknown)}"}

        try:
            if path.exists():
                cfg = load_cluster_config(path)
            else:
                cfg = self._default_cluster_config()
        except Exception as e:
            return {"status": "error", "message": f"Failed to load cluster config: {e}"}

        updates = {}
        for key in sorted([str(k) for k in fields.keys()]):
            raw_v = fields.get(key)
            if raw_v is None:
                updates[key] = "arkSA" if key == "cluster_name" else ""
                continue

            value = str(raw_v).strip()
            updates[key] = value or ("arkSA" if key == "cluster_name" else "")

        prev_cluster_name = str(cfg.cluster_name)
        new_cfg = replace(cfg, **updates).normalized()

        try:
            save_cluster_config(new_cfg, path)
        except Exception as e:
            return {"status": "error", "message": f"Failed to save cluster config: {e}"}

        mark_app_dirty = _orch_method(self._orchestrator, "_mark_app_setup_report_dirty")
        mark_instance_dirty = _orch_method(self._orchestrator, "_mark_instance_readiness_dirty")
        mark_plugin_dirty = _orch_method(self._orchestrator, "_mark_plugin_readiness_dirty")
        iter_instance_keys = _orch_method(self._orchestrator, "_iter_instance_keys")
        plugins_for_dependency = _orch_method(self._orchestrator, "_plugins_for_dependency")
        invalidate_runtime_summary = _orch_method(self._orchestrator, "_invalidate_runtime_summary")
        if callable(mark_app_dirty):
            changed_fields = {
                key
                for key, value in updates.items()
                if str(getattr(cfg, key, "") or "") != str(value or "")
            }
            if changed_fields.intersection({"gameservers_root", "steamcmd_root"}):
                mark_app_dirty()
            if "gameservers_root" in changed_fields:
                if callable(iter_instance_keys) and callable(mark_instance_dirty):
                    for plugin_name, instance_id in iter_instance_keys():
                        mark_instance_dirty(plugin_name, instance_id)
                elif callable(mark_instance_dirty):
                    mark_instance_dirty()
                if callable(invalidate_runtime_summary):
                    invalidate_runtime_summary()
            if "steamcmd_root" in changed_fields and callable(plugins_for_dependency):
                affected_plugins = list(plugins_for_dependency("steamcmd"))
                if callable(mark_plugin_dirty):
                    for plugin_name in affected_plugins:
                        mark_plugin_dirty(plugin_name)
                if callable(mark_instance_dirty):
                    for plugin_name in affected_plugins:
                        if callable(iter_instance_keys):
                            for affected_plugin, instance_id in iter_instance_keys(plugin_name):
                                mark_instance_dirty(affected_plugin, instance_id)
                        else:
                            mark_instance_dirty(plugin_name=plugin_name)

        warnings = []
        if "cluster_name" in updates and updates["cluster_name"] != prev_cluster_name:
            warnings.append("cluster_name changed; existing installs may resolve to a different folder.")

        return {
            "status": "success",
            "data": {
                "path": str(path),
                "fields": {
                    "gameservers_root": str(new_cfg.gameservers_root),
                    "cluster_name": str(new_cfg.cluster_name),
                    "steamcmd_root": str(getattr(new_cfg, "steamcmd_root", "") or ""),
                },
                "updated_fields": sorted(list(updates.keys())),
                "warnings": warnings,
            },
        }


    ############################################################
    # SECTION: Manual Backup (Delta-Only)
    ############################################################
    def backup_instance(self, plugin_name, instance_id, backup_root):
        if not backup_root:
            return {"status": "error", "message": "--backup-root is required"}

        state = self._orchestrator.get_instance_state(plugin_name, instance_id)
        if state != self._orchestrator._state_manager.STOPPED:
            return {"status": "error", "message": "Backup allowed only when instance is STOPPED"}

        cluster_root = getattr(self._orchestrator, "_cluster_root", None)
        if not cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}

        from pathlib import Path
        from core.backup import find_savedarks_dir, create_backup_zip, MANIFEST_NAME

        savedarks_dir = find_savedarks_dir(cluster_root, plugin_name, instance_id)

        dest_dir = Path(backup_root) / str(plugin_name) / str(instance_id)
        manifest_path = dest_dir / MANIFEST_NAME

        snapshot = create_backup_zip(
            savedarks_dir=savedarks_dir,
            backup_dest_dir=dest_dir,
            instance_id_fallback=str(instance_id),
            manifest_path=manifest_path,
        )

        payload = {
            "backup_path": snapshot.get("backup_path"),
            "files_included_count": snapshot.get("files_included_count"),
            "bytes_included_total": snapshot.get("bytes_included_total"),
            "map_name": snapshot.get("map_name"),
        }
        try:
            self._orchestrator._emit_event(
                "backup_created",
                plugin_name=plugin_name,
                instance_id=instance_id,
                payload=payload,
            )
        except Exception:
            pass

        return {"status": "success", "data": snapshot}

    ############################################################
    # SECTION: Manual Restore (Selective, STOPPED-Only)
    ############################################################
    def restore_instance(
        self,
        plugin_name,
        instance_id,
        backup_root,
        backup_zip,
        player_name=None,
        mode=None,
        files=None,
    ):
        if not backup_root:
            return {"status": "error", "message": "--backup-root is required"}
        if not backup_zip:
            return {"status": "error", "message": "--backup is required"}

        provided = [player_name is not None, mode is not None, files is not None]
        if sum(1 for x in provided if x) != 1:
            return {"status": "error", "message": "Exactly one selector is required: --player-name OR --mode OR --files"}

        state = self._orchestrator.get_instance_state(plugin_name, instance_id)
        if state != self._orchestrator._state_manager.STOPPED:
            return {"status": "error", "message": "Restore allowed only when instance is STOPPED"}

        cluster_root = getattr(self._orchestrator, "_cluster_root", None)
        if not cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}

        from pathlib import Path
        from core.restore import safe_list_zip_entries, resolve_selection, perform_restore

        backup_root_p = Path(backup_root)

        zip_p = Path(backup_zip)
        if not zip_p.is_absolute():
            zip_p = backup_root_p / str(plugin_name) / str(instance_id) / zip_p

        if not zip_p.exists():
            return {"status": "error", "message": f"Backup zip not found: {zip_p}"}

        try:
            entries = safe_list_zip_entries(zip_p)
            selection = resolve_selection(
                zip_entries=entries,
                backup_root=backup_root_p,
                plugin_name=str(plugin_name),
                instance_id=str(instance_id),
                selector_player_name=player_name,
                selector_mode=mode,
                selector_files=files,
            )
            snapshot = perform_restore(
                cluster_root=str(cluster_root),
                plugin_name=str(plugin_name),
                instance_id=str(instance_id),
                zip_path=zip_p,
                selection=selection,
            )
        except Exception as e:
            return {"status": "error", "message": str(e)}

        payload = {
            "backup_path": snapshot.get("backup_path"),
            "files_restored_count": snapshot.get("files_restored_count"),
            "mode": snapshot.get("selector_value") if snapshot.get("selector_kind") == "mode" else None,
            "player_name": snapshot.get("selector_value") if snapshot.get("selector_kind") == "player-name" else None,
            "selector_kind": snapshot.get("selector_kind"),
        }
        try:
            self._orchestrator._emit_event(
                "backup_restored",
                plugin_name=plugin_name,
                instance_id=instance_id,
                payload=payload,
            )
        except Exception:
            pass

        return {"status": "success", "data": snapshot}

    def validate_plugin(self, plugin_name, instance_id=None, strict: bool = False):
        payload = {
            "instance_id": (str(instance_id) if instance_id is not None else None),
            "strict": bool(strict),
        }
        return self._orchestrator.send_action(str(plugin_name), "validate", payload)

    def read_cached_instance_readiness_report(self, plugin_name, instance_id):
        fn = getattr(self._orchestrator, "read_cached_instance_readiness_report", None)
        if not callable(fn):
            fallback = getattr(self._orchestrator, "get_instance_readiness_report", None)
            if callable(fallback):
                return {"status": "success", "data": fallback(str(plugin_name), str(instance_id))}
            return {"status": "success", "data": {"ok": True, "plugin_name": str(plugin_name), "instance_id": str(instance_id), "status": "installed", "results": []}}
        return {"status": "success", "data": fn(str(plugin_name), str(instance_id))}

    def refresh_instance_readiness_report(self, plugin_name, instance_id):
        fn = getattr(self._orchestrator, "refresh_instance_readiness_report", None)
        if not callable(fn):
            return self.read_cached_instance_readiness_report(plugin_name, instance_id)
        return {"status": "success", "data": fn(str(plugin_name), str(instance_id))}

    def get_instance_readiness_report(self, plugin_name, instance_id):
        return self.read_cached_instance_readiness_report(plugin_name, instance_id)

    def ensure_plugin_registered(self, plugin_name: str, plugin_json: dict) -> None:
        """Register *plugin_name* from *plugin_json* if it is not already in the registry.

        Called by the dispatcher before routing a command so that plugins
        received via the backend catalog are available even when no local
        plugin files exist on the agent machine.
        """
        if not plugin_name or not isinstance(plugin_json, dict):
            return
        registry = getattr(self._orchestrator, "_registry", None)
        if registry is None or not hasattr(registry, "get"):
            return
        if registry.get(str(plugin_name)):
            return  # already loaded
        cluster_root = getattr(self._orchestrator, "_cluster_root", "") or ""
        if hasattr(registry, "register_from_json"):
            registry.register_from_json(str(plugin_name), plugin_json, cluster_root)

    def get_plugin_capabilities(self, plugin_name):
        registry = getattr(self._orchestrator, "_registry", None)
        if registry is None or not hasattr(registry, "get"):
            return {"status": "error", "message": "Plugin registry not available"}

        record = registry.get(str(plugin_name))
        if not isinstance(record, dict):
            return {"status": "error", "message": f"Unknown plugin: {plugin_name}"}

        metadata = record.get("metadata")
        if not isinstance(metadata, dict):
            return {"status": "success", "data": {"plugin_name": str(plugin_name), "capabilities": {}}}

        capabilities = metadata.get("capabilities")
        if not isinstance(capabilities, dict):
            capabilities = {}

        return {
            "status": "success",
            "data": {
                "plugin_name": str(plugin_name),
                "capabilities": dict(capabilities),
            },
        }

    def get_plugin_config_fields(self, plugin_name):
        cluster_root = getattr(self._orchestrator, "_cluster_root", None)
        if not cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}

        from core.plugin_config import editable_plugin_defaults_fields, load_plugin_defaults, plugin_defaults_path

        try:
            loaded = load_plugin_defaults(str(cluster_root), str(plugin_name))
        except Exception as e:
            return {"status": "error", "message": str(e)}

        fields = {}
        for key in editable_plugin_defaults_fields():
            if key in {"mods", "passive_mods"}:
                fields[key] = list(loaded.get(key, []))
            else:
                fields[key] = loaded.get(key)

        schema = {}
        metadata = {}
        if hasattr(self._orchestrator, "_registry") and hasattr(self._orchestrator._registry, "get_metadata"):
            metadata = self._orchestrator._registry.get_metadata(str(plugin_name)) or {}
        if isinstance(metadata.get("app_settings"), dict):
            schema = dict(metadata.get("app_settings") or {})

        return {
            "status": "success",
            "data": {
                "fields": fields,
                "schema": schema,
                "path": str(plugin_defaults_path(str(cluster_root), str(plugin_name))),
            },
        }

    def set_plugin_config_fields(self, plugin_name, fields):
        cluster_root = getattr(self._orchestrator, "_cluster_root", None)
        if not cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}
        if not isinstance(fields, dict):
            return {"status": "error", "message": "fields must be a dict"}

        from core.plugin_config import editable_plugin_defaults_fields, load_plugin_defaults, write_plugin_defaults_atomic

        allowed = set(editable_plugin_defaults_fields())
        unknown = sorted([str(k) for k in fields.keys() if str(k) not in allowed])
        if unknown:
            return {"status": "error", "message": f"Unknown plugin config fields: {', '.join(unknown)}"}

        try:
            current = load_plugin_defaults(str(cluster_root), str(plugin_name))
        except Exception as e:
            return {"status": "error", "message": str(e)}

        payload = {str(k): v for k, v in current.items() if not str(k).startswith("_")}
        payload["schema_version"] = 1

        for key, value in fields.items():
            ks = str(key)
            if ks in {"mods", "passive_mods"}:
                payload[ks] = [] if value is None else value
            elif value is None:
                payload.pop(ks, None)
            else:
                payload[ks] = value

        try:
            path = write_plugin_defaults_atomic(str(cluster_root), str(plugin_name), payload)
        except Exception as e:
            return {"status": "error", "message": str(e)}

        mark_plugin_dirty = _orch_method(self._orchestrator, "_mark_plugin_readiness_dirty")
        mark_instance_dirty = _orch_method(self._orchestrator, "_mark_instance_readiness_dirty")
        iter_instance_keys = _orch_method(self._orchestrator, "_iter_instance_keys")
        invalidate_runtime_summary = _orch_method(self._orchestrator, "_invalidate_runtime_summary")
        if callable(mark_plugin_dirty):
            mark_plugin_dirty(str(plugin_name))
        if callable(mark_instance_dirty):
            if callable(iter_instance_keys):
                for affected_plugin, instance_id in iter_instance_keys(str(plugin_name)):
                    mark_instance_dirty(affected_plugin, instance_id)
            else:
                mark_instance_dirty(plugin_name=str(plugin_name))
        if callable(invalidate_runtime_summary):
            invalidate_runtime_summary(str(plugin_name))

        sync_ini_fields = sorted([str(k) for k in fields.keys() if str(k) in self._INI_SYNC_FIELDS or str(k) == "display_name"])
        sync_method = _orch_method(self._orchestrator, "sync_instance_ini_fields")
        clear_instance_fields = _orch_method(self._orchestrator, "clear_instance_config_fields")
        iter_instance_keys = _orch_method(self._orchestrator, "_iter_instance_keys")
        changed_plugin_override_fields = sorted([str(k) for k in fields.keys() if str(k) in self._PLUGIN_PROPAGATED_INSTANCE_FIELDS])
        plugin_override_fields = sorted(self._PLUGIN_PROPAGATED_INSTANCE_FIELDS) if changed_plugin_override_fields else []
        if changed_plugin_override_fields:
            sync_ini_fields = sorted(set(sync_ini_fields) | set(plugin_override_fields))
        if callable(iter_instance_keys) and (sync_ini_fields or plugin_override_fields):
            for affected_plugin, instance_id in iter_instance_keys(str(plugin_name)):
                if callable(clear_instance_fields) and plugin_override_fields:
                    clear_instance_fields(str(affected_plugin), str(instance_id), plugin_override_fields)
                if callable(sync_method) and sync_ini_fields:
                    sync_method(str(affected_plugin), str(instance_id), sync_ini_fields)

        return {
            "status": "success",
            "data": {
                "path": str(path),
                "updated_fields": sorted([str(k) for k in fields.keys()]),
            },
        }

    def get_instance_plugin_config_fields(self, plugin_name, instance_id, fields=None):
        import json
        from core.plugin_config import resolve_instance_config_path

        cluster_root = getattr(self._orchestrator, "_cluster_root", None)
        if not cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}

        path = resolve_instance_config_path(str(cluster_root), str(plugin_name), str(instance_id))

        data = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(data, dict):
                    return {"status": "error", "message": f"Config must be a JSON object: {path}"}
            except Exception as e:
                return {"status": "error", "message": f"Failed to parse config: {e}"}

        if fields is None:
            selected = dict(data)
        else:
            selected = {}
            for k in fields:
                ks = str(k)
                if ks in data:
                    selected[ks] = data[ks]

        schema = {}
        metadata = {}
        if hasattr(self._orchestrator, "_registry") and hasattr(self._orchestrator._registry, "get_metadata"):
            metadata = self._orchestrator._registry.get_metadata(str(plugin_name)) or {}
        if isinstance(metadata.get("server_settings"), dict):
            schema = dict(metadata.get("server_settings") or {})

        return {"status": "success", "data": {"fields": selected, "schema": schema, "path": str(path)}}

    def set_instance_plugin_config_fields(self, plugin_name, instance_id, fields):
        import json
        import os
        import tempfile
        from core.plugin_config import instance_config_path, legacy_instance_config_path

        cluster_root = getattr(self._orchestrator, "_cluster_root", None)
        if not cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}

        if not isinstance(fields, dict):
            return {"status": "error", "message": "fields must be a dict"}

        path = instance_config_path(str(cluster_root), str(plugin_name), str(instance_id))

        current = {}
        if path.exists():
            try:
                current = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(current, dict):
                    return {"status": "error", "message": f"Config must be a JSON object: {path}"}
            except Exception as e:
                return {"status": "error", "message": f"Failed to parse config: {e}"}

        for k, v in fields.items():
            ks = str(k)
            if v is None:
                current.pop(ks, None)
            else:
                current[ks] = v

        if "schema_version" not in current:
            current["schema_version"] = 1

        payload = json.dumps(current, indent=2, sort_keys=True) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)

        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, path)
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass

        legacy_path = legacy_instance_config_path(str(cluster_root), str(plugin_name), str(instance_id))
        if legacy_path != path and legacy_path.exists():
            legacy_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=legacy_path.name + ".", dir=str(legacy_path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(payload)
                os.replace(tmp, legacy_path)
            finally:
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except OSError:
                    pass

        mark_instance_dirty = _orch_method(self._orchestrator, "_mark_instance_readiness_dirty")
        invalidate_runtime_summary = _orch_method(self._orchestrator, "_invalidate_runtime_summary")
        if callable(mark_instance_dirty):
            mark_instance_dirty(str(plugin_name), str(instance_id))
        if callable(invalidate_runtime_summary):
            invalidate_runtime_summary(str(plugin_name), str(instance_id))

        sync_ini_fields = sorted([str(k) for k in fields.keys() if str(k) in self._INI_SYNC_FIELDS])
        sync_result = None
        sync_method = _orch_method(self._orchestrator, "sync_instance_ini_fields")
        if callable(sync_method) and sync_ini_fields:
            sync_result = sync_method(str(plugin_name), str(instance_id), sync_ini_fields)

        return {
            "status": "success",
            "data": {
                "path": str(path),
                "updated_fields": sorted([str(k) for k in fields.keys()]),
                "apply_result": sync_result,
            },
        }

    def _resolve_instance_path_context(self, plugin_name, instance_id):
        from pathlib import Path
        import json
        import os
        from core.plugin_config import resolve_instance_config_path, resolve_plugin_defaults_path

        def _install_folder_name(raw_value):
            raw = str(raw_value or "ArkSA").strip()
            if not raw:
                return "ArkSA"
            normalized = raw.replace("/", os.sep).replace("\\", os.sep).rstrip("\\/")
            leaf = os.path.basename(normalized)
            return leaf or "ArkSA"

        def _managed_base_dir(gameservers_root, defaults_install_root, install_folder):
            explicit = str(defaults_install_root or "").strip()
            if explicit:
                explicit_path = Path(explicit)
                if explicit_path.is_absolute():
                    return explicit_path
                return Path(str(gameservers_root)) / explicit
            return Path(str(gameservers_root)) / str(install_folder)

        def _managed_install_root(gameservers_root, defaults_install_root, install_folder, map_name, explicit_install_root):
            if not gameservers_root or not map_name:
                return None

            base_dir = _managed_base_dir(gameservers_root, defaults_install_root, install_folder)
            explicit = str(explicit_install_root or "").strip()
            if explicit:
                try:
                    if Path(explicit).resolve().parent == base_dir.resolve():
                        return explicit
                    if Path(str(gameservers_root)).resolve() in Path(explicit).resolve().parents:
                        return explicit
                except Exception:
                    if Path(explicit).parent == base_dir:
                        return explicit
                    if Path(str(gameservers_root)) in Path(explicit).parents:
                        return explicit
                if Path(explicit).is_absolute():
                    return None

            next_suffix = 1
            if base_dir.exists() and base_dir.is_dir():
                prefix = f"{map_name}_"
                for entry in base_dir.iterdir():
                    if not entry.is_dir():
                        continue
                    name = str(entry.name)
                    if not name.startswith(prefix):
                        continue
                    try:
                        suffix = int(name[len(prefix):])
                    except Exception:
                        continue
                    if suffix >= next_suffix:
                        next_suffix = suffix + 1
            return str(base_dir / f"{map_name}_{next_suffix}")

        cluster_root = getattr(self._orchestrator, "_cluster_root", None)
        if not cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}

        warnings = []
        errors = []
        plugin_name = str(plugin_name)
        instance_id = str(instance_id)

        inst_path = resolve_instance_config_path(str(cluster_root), plugin_name, instance_id)
        plugin_defaults_path = resolve_plugin_defaults_path(str(cluster_root), plugin_name)

        inst = {}
        defaults = {}
        try:
            if inst_path.exists():
                raw = json.loads(inst_path.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict):
                    inst = raw
                else:
                    errors.append(f"Instance config must be object: {inst_path}")
            else:
                errors.append(f"Instance config not found: {inst_path}")

            if plugin_defaults_path.exists():
                raw = json.loads(plugin_defaults_path.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict):
                    defaults = raw
                else:
                    errors.append(f"Plugin config must be object: {plugin_defaults_path}")
        except Exception as e:
            return {"status": "error", "message": f"Failed to load path preview inputs: {e}"}

        cluster_cfg = self.get_cluster_config_fields(["gameservers_root", "cluster_name"])
        
        cluster_fields = {}
        if isinstance(cluster_cfg, dict) and cluster_cfg.get("status") == "success":
            cluster_fields = cluster_cfg.get("data", {}).get("fields", {}) or {}

        map_name = str(inst.get("map") or "").strip()
        gameservers_root = str(
            inst.get("gameservers_root")
            or defaults.get("gameservers_root")
            or cluster_fields.get("gameservers_root")
            or ""
        ).strip()
        install_folder = _install_folder_name(defaults.get("install_folder"))
        managed_install_root = _managed_install_root(
            gameservers_root,
            defaults.get("install_root"),
            install_folder,
            map_name,
            inst.get("install_root"),
        )

        canonical = {
            "steamcmd_dir": None,
            "cluster_dir": None,
            "map_dir": None,
            "server_dir": None,
            "logs_dir": None,
            "tmp_dir": None,
        }
        if managed_install_root:
            canonical["steamcmd_dir"] = str(Path(gameservers_root) / "steamcmd")
            canonical["cluster_dir"] = None
            canonical["map_dir"] = str(Path(managed_install_root))
            canonical["server_dir"] = str(Path(managed_install_root))
            canonical["logs_dir"] = str(Path(managed_install_root) / "logs")
            canonical["tmp_dir"] = str(Path(managed_install_root) / "tmp")
        else:
            if not gameservers_root:
                warnings.append("gameservers_root is not configured; canonical paths incomplete.")
            if not map_name:
                warnings.append("map_name is not configured; canonical paths incomplete.")

        legacy_install_root = inst.get("install_root")
        legacy = {
            "install_root": None,
            "server_dir": None,
            "logs_dir": None,
        }
        if legacy_install_root:
            legacy["install_root"] = str(legacy_install_root)
            legacy["server_dir"] = str(Path(str(legacy_install_root)) / "asa_server")
            legacy["logs_dir"] = str(Path(str(legacy_install_root)) / "logs")

        using_legacy = bool(legacy["install_root"] and not managed_install_root)
        if using_legacy:
            warnings.append("Using legacy install_root fallback (canonical inputs missing).")

        return {
            "status": "success",
            "data": {
                "plugin_name": plugin_name,
                "instance_id": instance_id,
                "map_name": map_name,
                "using_legacy_install_root": bool(using_legacy),
                "canonical": canonical,
                "legacy": legacy,
                "warnings": warnings,
                "errors": errors,
            },
        }

    def get_instance_path_preview(self, plugin_name, instance_id):
        return self._resolve_instance_path_context(plugin_name, instance_id)

    def get_log_tail(self, plugin_name, instance_id, log_name, last_lines=200):
        from pathlib import Path

        resolved = self._resolve_instance_path_context(plugin_name, instance_id)
        if not isinstance(resolved, dict) or resolved.get("status") != "success":
            return resolved

        try:
            n = int(last_lines)
        except Exception:
            n = 200
        if n <= 0:
            n = 200
        if n > 2000:
            n = 2000

        data = resolved.get("data") or {}
        canonical = data.get("canonical") if isinstance(data, dict) else {}
        legacy = data.get("legacy") if isinstance(data, dict) else {}
        logs_root = ""
        if isinstance(canonical, dict):
            logs_root = str(canonical.get("logs_dir") or "").strip()
        if not logs_root and isinstance(legacy, dict):
            logs_root = str(legacy.get("logs_dir") or "").strip()
        if not logs_root:
            return {"status": "error", "message": "log root not configured (needs gameservers_root+map or legacy install_root)"}

        log_key = str(log_name).strip().lower()
        if log_key.endswith(".log"):
            file_name = log_key
        else:
            file_name = f"{log_key}.log"

        path = Path(logs_root) / file_name
        if not path.exists() or not path.is_file():
            return {
                "status": "success",
                "data": {
                    "log_name": file_name,
                    "path": str(path),
                    "found": False,
                    "lines": [],
                    "text": "",
                    "last_lines": n,
                },
            }

        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as e:
            return {"status": "error", "message": f"Failed to read log: {e}"}

        tail = lines[-n:] if len(lines) > n else lines
        return {
            "status": "success",
            "data": {
                "log_name": file_name,
                "path": str(path),
                "found": True,
                "lines": tail,
                "text": "\n".join(tail),
                "last_lines": n,
            },
        }

    def get_install_progress(self, plugin_name, instance_id, last_lines=50):
        from pathlib import Path
        import json
        import re

        resolved = self._resolve_instance_path_context(plugin_name, instance_id)
        if not isinstance(resolved, dict) or resolved.get("status") != "success":
            return resolved

        try:
            n = int(last_lines)
        except Exception:
            n = 50
        if n <= 0:
            n = 50
        if n > 500:
            n = 500

        data = resolved.get("data") or {}
        canonical = data.get("canonical") if isinstance(data, dict) else {}
        legacy = data.get("legacy") if isinstance(data, dict) else {}
        logs_root = ""
        if isinstance(canonical, dict):
            logs_root = str(canonical.get("logs_dir") or "").strip()
        if not logs_root and isinstance(legacy, dict):
            logs_root = str(legacy.get("logs_dir") or "").strip()
        if not logs_root:
            return {"status": "error", "message": "log root not configured (needs gameservers_root+map or legacy install_root)"}

        logs_path = Path(logs_root)
        install_log_path = logs_path / "install_server.log"
        steamcmd_log_path = logs_path / "steamcmd_install.log"
        progress_metadata_path = logs_path / "steamcmd_progress_source.json"

        def _tail(path: Path):
            if not path.exists() or not path.is_file():
                return False, []
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                return False, []
            tail = lines[-n:] if len(lines) > n else lines
            return True, tail

        metadata = None
        if progress_metadata_path.exists() and progress_metadata_path.is_file():
            try:
                raw = json.loads(progress_metadata_path.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict):
                    metadata = raw
            except Exception:
                metadata = None

        install_found, install_tail = _tail(install_log_path)
        steamcmd_found, steamcmd_tail = _tail(steamcmd_log_path)

        def _parse_steamcmd_progress(lines):
            phase = None
            percent = None
            current = None
            total = None
            completed = False
            for raw_line in lines:
                line = str(raw_line or "").strip()
                if not line:
                    continue
                lowered = line.lower()
                match = re.search(
                    r"Update state \((0x[0-9a-fA-F]+)\)\s+([^,]+),\s+progress:\s+([0-9]+(?:\.[0-9]+)?)\s+\(([0-9]+)\s*/\s*([0-9]+)\)",
                    line,
                )
                if match:
                    phase_text = str(match.group(2) or "").strip().lower()
                    if "verifying" in phase_text or "validate" in phase_text:
                        phase = "validating"
                    elif "downloading" in phase_text:
                        phase = "downloading"
                    else:
                        phase = phase_text or phase
                    percent = float(match.group(3))
                    current = int(match.group(4))
                    total = int(match.group(5))
                    continue
                if "fully installed" in lowered or "success! app" in lowered:
                    completed = True
            return {
                "phase": phase,
                "percent": percent,
                "current_bytes": current,
                "total_bytes": total,
                "completed": completed,
            }

        steamcmd_progress = _parse_steamcmd_progress(steamcmd_tail)

        progress_state = "not_started"
        if metadata is not None or install_found or steamcmd_found:
            progress_state = "running"
        if steamcmd_progress.get("phase") == "validating":
            progress_state = "validating"
        if install_tail and any("steamcmd install complete" in str(line).lower() for line in install_tail):
            progress_state = "completed"
        if steamcmd_progress.get("completed"):
            progress_state = "completed"
        if install_tail and any("failed" in str(line).lower() or "timeout" in str(line).lower() for line in install_tail):
            progress_state = "failed"

        return {
            "status": "success",
            "data": {
                "plugin_name": str(plugin_name),
                "instance_id": str(instance_id),
                "state": progress_state,
                "paths": {
                    "logs_dir": str(logs_path),
                    "install_log": str(install_log_path),
                    "steamcmd_log": str(steamcmd_log_path),
                    "progress_metadata": str(progress_metadata_path),
                },
                "progress_metadata": metadata,
                "steamcmd_progress": steamcmd_progress,
                "install_log_found": install_found,
                "install_log_tail": install_tail,
                "steamcmd_log_found": steamcmd_found,
                "steamcmd_log_tail": steamcmd_tail,
                "last_lines": n,
            },
        }

    ############################################################
    # SECTION: Provisioning / Onboarding (Validate + Add Instance)
    ############################################################
    def validate_environment(self, cluster_root, backup_root=None, strict: bool = False):
        from pathlib import Path
        import os
        import json

        checks = []
        warnings = []

        def add_check(name, ok, message=""):
            checks.append({"name": str(name), "ok": bool(ok), "message": str(message)})

        def add_warn(name, message=""):
            warnings.append({"name": str(name), "message": str(message)})

        root = Path(cluster_root) if cluster_root is not None else Path("")
        root_exists = root.exists() and root.is_dir()
        add_check("cluster_root_exists", root_exists, "" if root_exists else "cluster_root does not exist or is not a directory")

        root_writable = False
        if root_exists:
            root_writable = os.access(str(root), os.W_OK)
        add_check("cluster_root_writable", root_writable, "" if root_writable else "cluster_root is not writable")

        plugin_ok = False
        plugin_msg = ""
        registry = None
        try:
            from core.plugin_registry import PluginRegistry

            plugin_dir = root / "plugins"
            if not (plugin_dir.exists() and plugin_dir.is_dir()):
                raise ValueError("plugins directory missing under cluster_root")

            registry = PluginRegistry(plugin_dir=str(plugin_dir))
            registry.load_all()
            plugin_ok = True
        except Exception as e:
            plugin_ok = False
            plugin_msg = str(e)

        add_check("plugin_registry_can_load", plugin_ok, plugin_msg)

        instances_ok = True
        instances_msg = ""
        try:
            plugins_dir = root / "plugins"
            if plugins_dir.exists() and plugins_dir.is_dir():
                for plugin_dir in sorted([p for p in plugins_dir.iterdir() if p.is_dir()], key=lambda p: p.name):
                    inst_parent = plugin_dir / "instances"
                    if not inst_parent.exists():
                        continue
                    if not inst_parent.is_dir():
                        instances_ok = False
                        instances_msg = f"{inst_parent} is not a directory"
                        break

                    for inst_dir in sorted([p for p in inst_parent.iterdir() if p.is_dir()], key=lambda p: p.name):
                        for req in ("config", "data", "logs", "backups"):
                            rp = inst_dir / req
                            if not rp.exists() or not rp.is_dir():
                                instances_ok = False
                                instances_msg = f"Missing required dir: {rp}"
                                break
                        if not instances_ok:
                            break

                        meta = inst_dir / "instance.json"
                        if not meta.exists() or not meta.is_file():
                            instances_ok = False
                            instances_msg = f"Missing instance.json: {meta}"
                            break

                        try:
                            payload = json.loads(meta.read_text(encoding="utf-8-sig"))
                        except Exception:
                            instances_ok = False
                            instances_msg = f"Invalid JSON: {meta}"
                            break

                        if int(payload.get("schema_version", 0)) != 1:
                            instances_ok = False
                            instances_msg = f"schema_version != 1 in {meta}"
                            break
                        if not payload.get("plugin_name") or not payload.get("instance_id"):
                            instances_ok = False
                            instances_msg = f"Missing plugin_name/instance_id in {meta}"
                            break
                        if payload.get("install_status") is None:
                            instances_ok = False
                            instances_msg = f"Missing install_status in {meta}"
                            break
        except Exception as e:
            instances_ok = False
            instances_msg = str(e)

        add_check("existing_instances_structurally_valid", instances_ok, instances_msg)

        ark_ready = True
        if (root / "plugins" / "ark").exists() and (root / "plugins" / "ark").is_dir():
            from core.plugin_config import resolve_plugin_defaults_path
            cfg_path = resolve_plugin_defaults_path(str(root), "ark")
            if cfg_path.exists():
                try:
                    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
                    if isinstance(cfg, dict):
                        if "test_mode" not in cfg:
                            add_warn("ark_test_mode_missing", f"{cfg_path} missing test_mode (treated as TEST MODE).")
                            if strict:
                                ark_ready = False
                        else:
                            if bool(cfg.get("test_mode")) is True:
                                add_warn("ark_test_mode_enabled", f"{cfg_path} test_mode is true (TEST MODE).")
                                if strict:
                                    ark_ready = False
                    else:
                        add_warn("ark_plugin_config_invalid", f"{cfg_path} must be a JSON object.")
                except Exception:
                    add_warn("ark_plugin_config_invalid", f"{cfg_path} is invalid JSON.")

        add_check("ark_strict_ready", (ark_ready if strict else True), "")

        plugins_validate_ok = True
        plugins_validate_msg = ""
        try:
            can_iter = (
                registry is not None
                and hasattr(registry, "list_all")
                and hasattr(registry, "get")
            )
            if can_iter and registry is not None:
                registry_obj = registry
                for plugin_name in sorted(registry_obj.list_all()):
                    rec = registry_obj.get(plugin_name) or {}
                    conn = rec.get("connection") if isinstance(rec, dict) else None
                    if conn is None or not hasattr(conn, "send_request"):
                        continue
                    resp = conn.send_request("validate", {"strict": bool(strict)})
                    if not isinstance(resp, dict) or resp.get("status") != "success":
                        plugins_validate_ok = False
                        plugins_validate_msg = f"Plugin validate failed: {plugin_name}"
                        break
        except Exception as e:
            plugins_validate_ok = False
            plugins_validate_msg = str(e)

        add_check("plugins_validate", plugins_validate_ok, plugins_validate_msg)

        if backup_root is not None:
            br = Path(backup_root)
            br_exists = br.exists() and br.is_dir()
            add_check("backup_root_exists", br_exists, "" if br_exists else "backup_root does not exist or is not a directory")

            br_writable = False
            if br_exists:
                br_writable = os.access(str(br), os.W_OK)
            add_check("backup_root_writable", br_writable, "" if br_writable else "backup_root is not writable")

        ok = all(c["ok"] for c in checks)

        try:
            if registry is not None and hasattr(registry, "_plugins"):
                for _name, rec in list(registry._plugins.items()):
                    proc = rec.get("process")
                    try:
                        if proc is not None and proc.is_alive():
                            proc.terminate()
                            proc.join(timeout=1)
                    except Exception:
                        pass
        except Exception:
            pass

        return {
            "ok": bool(ok),
            "cluster_root": str(cluster_root),
            "backup_root": str(backup_root) if backup_root is not None else None,
            "checks": checks,
            "warnings": warnings,
            "strict": bool(strict),
        }

    def add_instance(self, plugin_name, instance_id):
        cluster_root = getattr(self._orchestrator, "_cluster_root", None)
        if not cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}

        from core.instance_layout import get_instance_root, ensure_instance_layout

        inst_root = get_instance_root(cluster_root, str(plugin_name), str(instance_id))
        meta_path = inst_root / "instance.json"
        existed = meta_path.exists()

        snapshot = ensure_instance_layout(cluster_root, str(plugin_name), str(instance_id))
        mark_instance_dirty = _orch_method(self._orchestrator, "_mark_instance_readiness_dirty")
        invalidate_runtime_summary = _orch_method(self._orchestrator, "_invalidate_runtime_summary")
        if callable(mark_instance_dirty):
            mark_instance_dirty(str(plugin_name), str(instance_id))
        if callable(invalidate_runtime_summary):
            invalidate_runtime_summary(str(plugin_name), str(instance_id))

        return {
            "status": "success",
            "data": {
                "action": "already_exists" if existed else "created",
                "plugin_name": str(plugin_name),
                "instance_id": str(instance_id),
                "snapshot": snapshot,
            },
        }

    def install_instance(self, plugin_name, instance_id):
        state = self._orchestrator.get_instance_state(plugin_name, instance_id)
        if state != self._orchestrator._state_manager.STOPPED:
            return {"status": "error", "message": "Install allowed only when instance is STOPPED"}

        cluster_root = getattr(self._orchestrator, "_cluster_root", None)
        if not cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}

        result = self._orchestrator.install_instance(plugin_name, instance_id)
        return result

    def install_deps(self, plugin_name, instance_id):
        return self._orchestrator.send_action(
            str(plugin_name),
            "install_deps",
            {"instance_id": str(instance_id)},
        )

    # NEW: install_server (Ark plugin-owned SteamCMD install/update)
    def install_server(self, plugin_name, instance_id):
        fn = getattr(self._orchestrator, "install_server_instance", None)
        if callable(fn):
            return fn(str(plugin_name), str(instance_id))

        # Back-compat fallback for older orchestrator stubs/tests.
        return self._orchestrator.send_action(
            str(plugin_name),
            "install_server",
            {"instance_id": str(instance_id)},
        )

    def update_instance(self, plugin_name, instance_id):
        fn = getattr(self._orchestrator, "update_instance", None)
        if callable(fn):
            return fn(str(plugin_name), str(instance_id))
        return self.install_server(str(plugin_name), str(instance_id))

    def check_update(self, plugin_name, instance_id):
        fn = getattr(self._orchestrator, "check_update", None)
        if callable(fn):
            return fn(str(plugin_name), str(instance_id))

        return self._orchestrator.send_action(
            str(plugin_name),
            "check_update",
            {"instance_id": str(instance_id)},
        )

    def check_plugin_update(self, plugin_name):
        fn = getattr(self._orchestrator, "check_plugin_update", None)
        if callable(fn):
            return fn(str(plugin_name))

        return self._orchestrator.send_action(
            str(plugin_name),
            "check_update",
            {"install_target": "master"},
        )

    def prepare_master_install(self, plugin_name):
        fn = getattr(self._orchestrator, "prepare_master_install", None)
        if callable(fn):
            return fn(str(plugin_name))

        return self._orchestrator.send_action(
            str(plugin_name),
            "install_server",
            {"install_target": "master"},
        )

    def discover_servers(self, plugin_name):
        fn = getattr(self._orchestrator, "discover_servers", None)
        if callable(fn):
            return fn(str(plugin_name))

        return self._orchestrator.send_action(
            str(plugin_name),
            "discover_servers",
            {},
        )

    def allocate_instance_ports(self, plugin_name):
        fn = getattr(self._orchestrator, "allocate_instance_ports", None)
        if callable(fn):
            return fn(str(plugin_name))
        return {"status": "error", "message": "Orchestrator missing allocate_instance_ports()"}

    def suggest_next_instance_id(self, plugin_name):
        fn = getattr(self._orchestrator, "suggest_next_instance_id", None)
        if callable(fn):
            return fn(str(plugin_name))
        return {"status": "error", "message": "Orchestrator missing suggest_next_instance_id()"}

    def import_server(self, plugin_name, candidate):
        fn = getattr(self._orchestrator, "import_server", None)
        if callable(fn):
            return fn(str(plugin_name), dict(candidate or {}))
        return {"status": "error", "message": "Orchestrator missing import_server()"}

    def remove_instance(self, plugin_name, instance_id, delete_files=False):
        fn = getattr(self._orchestrator, "remove_instance", None)
        if callable(fn):
            return fn(str(plugin_name), str(instance_id), delete_files=bool(delete_files))
        return {"status": "error", "message": "Orchestrator missing remove_instance()"}

    def start_instance(self, plugin_name, instance_id):
        return self._orchestrator.start_instance(plugin_name, instance_id)

    def stop_instance(self, plugin_name, instance_id):
        return self._orchestrator.stop_instance(plugin_name, instance_id)

    def restart_instance(self, plugin_name, instance_id, restart_reason="manual"):
        return self._orchestrator.restart_instance(plugin_name, instance_id, restart_reason=restart_reason)

    def rcon_exec(self, plugin_name, instance_id, command):
        return self._orchestrator.send_action(
            str(plugin_name),
            "rcon_exec",
            {"instance_id": str(instance_id), "command": str(command)},
        )

    def inspect_runtime_status(self, plugin_name, instance_id):
        # Explicit deep runtime inspect surface. This must not be used by
        # dashboard refresh or snapshot assembly code.
        inspect_fn = getattr(self._orchestrator, "inspect_runtime_status", None)
        if callable(inspect_fn):
            return inspect_fn(str(plugin_name), str(instance_id))
        return self._orchestrator.send_action(
            str(plugin_name),
            "runtime_status",
            {"instance_id": str(instance_id)},
        )

    def get_runtime_status(self, plugin_name, instance_id):
        # Compatibility alias retained for CLI/manual surfaces.
        return self.inspect_runtime_status(plugin_name, instance_id)

    def disable_instance(self, plugin_name, instance_id, reason="manual"):
        return self._orchestrator.disable_instance(plugin_name, instance_id, reason=reason)

    def enable_instance(self, plugin_name, instance_id, reason="manual"):
        return self._orchestrator.reenable_instance(plugin_name, instance_id, reason=reason)

    def configure_instance(
        self,
        plugin_name,
        instance_id,
        map_name,
        game_port,
        rcon_port,
        mods=None,
        passive_mods=None,
        map_mod=None,
    ):
        fn = getattr(self._orchestrator, "configure_instance_config", None)
        if fn is None:
            return {"status": "error", "message": "configure not available (orchestrator not updated yet)"}

        return fn(
            plugin_name=str(plugin_name),
            instance_id=str(instance_id),
            map_name=str(map_name),
            map_mod=map_mod,
            mods=mods or [],
            passive_mods=passive_mods or [],
            game_port=int(game_port),
            rcon_port=int(rcon_port),
        )

    def show_config(self, plugin_name, instance_id):
        fn = getattr(self._orchestrator, "show_instance_config", None)
        if fn is None:
            return {"status": "error", "message": "show-config not available (orchestrator not updated yet)"}

        return fn(
            plugin_name=str(plugin_name),
            instance_id=str(instance_id),
        )















