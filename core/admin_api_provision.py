############################################################
# SECTION: Admin API — Provision Surface
# Purpose:
#     Environment validation, instance provisioning, and
#     all thin lifecycle-delegate methods. Mixin for AdminAPI.
# Lifecycle Ownership:
#     None (delegation only)
# Constraints:
#     - No lifecycle authority
#     - Orchestrator remains sole lifecycle authority
############################################################


class _AdminAPIProvisionMixin:

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
        mark_instance_dirty = self._get_optional_orchestrator_method("_mark_instance_readiness_dirty")
        invalidate_runtime_summary = self._get_optional_orchestrator_method("_invalidate_runtime_summary")
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



















