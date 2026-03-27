############################################################
# SECTION: Admin API — Config Surface
# Purpose:
#     Cluster config, plugin config, and instance config
#     read/write methods. Mixin for AdminAPI.
# Lifecycle Ownership:
#     None (delegation + filesystem I/O only)
# Constraints:
#     - No lifecycle authority
#     - No orchestrator state mutation
############################################################

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.orchestrator import Orchestrator


class _AdminAPIConfigMixin:
    _orchestrator: "Orchestrator"
    _INI_SYNC_FIELDS = {"mods", "passive_mods", "max_players", "game_port", "rcon_port", "rcon_enabled", "admin_password", "server_name", "display_name"}
    _PLUGIN_PROPAGATED_INSTANCE_FIELDS = {"rcon_enabled", "admin_password", "pve"}

    def _get_optional_orchestrator_method(self, name: str) -> Any:
        orchestrator = getattr(self, "_orchestrator", None)
        if orchestrator is None:
            return None
        return getattr(orchestrator, name, None)

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

        mark_app_dirty = self._get_optional_orchestrator_method("_mark_app_setup_report_dirty")
        mark_instance_dirty = self._get_optional_orchestrator_method("_mark_instance_readiness_dirty")
        mark_plugin_dirty = self._get_optional_orchestrator_method("_mark_plugin_readiness_dirty")
        iter_instance_keys = self._get_optional_orchestrator_method("_iter_instance_keys")
        plugins_for_dependency = self._get_optional_orchestrator_method("_plugins_for_dependency")
        invalidate_runtime_summary = self._get_optional_orchestrator_method("_invalidate_runtime_summary")
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

        return {"status": "success", "data": {"fields": fields, "schema": schema, "path": str(plugin_defaults_path(str(cluster_root), str(plugin_name)))}}

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

        mark_plugin_dirty = self._get_optional_orchestrator_method("_mark_plugin_readiness_dirty")
        mark_instance_dirty = self._get_optional_orchestrator_method("_mark_instance_readiness_dirty")
        iter_instance_keys = self._get_optional_orchestrator_method("_iter_instance_keys")
        invalidate_runtime_summary = self._get_optional_orchestrator_method("_invalidate_runtime_summary")
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
        sync_method = self._get_optional_orchestrator_method("sync_instance_ini_fields")
        clear_instance_fields = self._get_optional_orchestrator_method("clear_instance_config_fields")
        iter_instance_keys = self._get_optional_orchestrator_method("_iter_instance_keys")
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

        mark_instance_dirty = self._get_optional_orchestrator_method("_mark_instance_readiness_dirty")
        invalidate_runtime_summary = self._get_optional_orchestrator_method("_invalidate_runtime_summary")
        if callable(mark_instance_dirty):
            mark_instance_dirty(str(plugin_name), str(instance_id))
        if callable(invalidate_runtime_summary):
            invalidate_runtime_summary(str(plugin_name), str(instance_id))

        sync_ini_fields = sorted([str(k) for k in fields.keys() if str(k) in self._INI_SYNC_FIELDS])
        sync_result = None
        sync_method = self._get_optional_orchestrator_method("sync_instance_ini_fields")
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

    ############################################################
