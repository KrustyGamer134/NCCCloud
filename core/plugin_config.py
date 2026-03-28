############################################################
# SECTION: Plugin-Owned Config Helpers (Core Library)
# Purpose:
#     Deterministic helpers used by Core CLI/AdminAPI to manage
#     plugin-owned config files without assuming plugin internals.
#
# Phase:
#     CG-PLUGIN-CONFIG-1
#
# Constraints:
#     - Deterministic (no wall-clock)
#     - No threads/async
#     - Atomic writes for plugin + instance config
############################################################

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import os
import tempfile
from core.instance_layout import get_instance_root


class PluginConfigError(Exception):
    pass
SCHEMA_VERSION = 1
_PLUGIN_DEFAULT_STRING_FIELDS = (
    "server_executable",
    "install_root",
    "admin_password",
    "cluster_id",
    "display_name",
    "scheduled_restart_time",
    "scheduled_update_check_time",
)
_PLUGIN_DEFAULT_INT_FIELDS = (
    "default_game_port_start",
    "default_rcon_port_start",
    "max_players",
)
_PLUGIN_DEFAULT_BOOL_FIELDS = (
    "rcon_enabled",
    "pve",
    "auto_update_on_restart",
    "scheduled_restart_enabled",
    "scheduled_update_check_enabled",
    "scheduled_update_auto_apply",
)


def plugin_defaults_path(cluster_root: str, plugin_name: str) -> Path:
    return Path(cluster_root) / "plugins" / str(plugin_name) / "plugin_defaults.json"


def legacy_plugin_defaults_path(cluster_root: str, plugin_name: str) -> Path:
    return Path(cluster_root) / "plugins" / str(plugin_name) / "plugin_config.json"


def instance_config_path(cluster_root: str, plugin_name: str, instance_id: str) -> Path:
    return get_instance_root(cluster_root, plugin_name, instance_id) / "config" / "instance_config.json"


def legacy_instance_config_path(cluster_root: str, plugin_name: str, instance_id: str) -> Path:
    return get_instance_root(cluster_root, plugin_name, instance_id) / "config" / "plugin_instance_config.json"


def resolve_plugin_defaults_path(cluster_root: str, plugin_name: str) -> Path:
    canonical = plugin_defaults_path(cluster_root, plugin_name)
    if canonical.exists():
        return canonical
    legacy = legacy_plugin_defaults_path(cluster_root, plugin_name)
    if legacy.exists():
        return legacy
    return canonical


def resolve_instance_config_path(cluster_root: str, plugin_name: str, instance_id: str) -> Path:
    canonical = instance_config_path(cluster_root, plugin_name, instance_id)
    if canonical.exists():
        return canonical
    legacy = legacy_instance_config_path(cluster_root, plugin_name, instance_id)
    if legacy.exists():
        return legacy
    return canonical


def editable_plugin_defaults_fields() -> Tuple[str, ...]:
    return (
        "mods",
        "passive_mods",
        "test_mode",
        "install_root",
        "admin_password",
        "cluster_id",
        "rcon_enabled",
        "pve",
        "auto_update_on_restart",
        "scheduled_restart_enabled",
        "scheduled_restart_time",
        "scheduled_update_check_enabled",
        "scheduled_update_check_time",
        "scheduled_update_auto_apply",
        "max_players",
        "default_game_port_start",
        "default_rcon_port_start",
        "display_name",
    )
def _plugin_defaults_fallback(path: Optional[Path] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mods": [],
        "passive_mods": [],
    }
    if path is not None:
        payload["_load_error"] = f"missing_file:{path}"
    return payload


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as e:
        raise PluginConfigError(f"Failed to read {path}: {e}") from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise PluginConfigError(f"Invalid JSON in {path}: {e}") from e

    if not isinstance(data, dict):
        raise PluginConfigError(f"Config must be an object: {path}")
    return data


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"

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


def _write_json_with_legacy_mirror(canonical_path: Path, legacy_path: Path, data: Dict[str, Any]) -> None:
    _write_json_atomic(canonical_path, data)
    if legacy_path != canonical_path and legacy_path.exists():
        _write_json_atomic(legacy_path, data)


def _normalize_plugin_defaults(raw: Dict[str, Any], *, path: Optional[Path] = None) -> Dict[str, Any]:
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise PluginConfigError("plugin defaults schema_version must be 1")

    mods = raw.get("mods", [])
    passive = raw.get("passive_mods", [])

    if not isinstance(mods, list) or not all(isinstance(x, str) for x in mods):
        raise PluginConfigError("plugin defaults mods must be list[str]")

    if not isinstance(passive, list) or not all(isinstance(x, str) for x in passive):
        raise PluginConfigError("plugin defaults passive_mods must be list[str]")

    _ensure_no_dupes(mods, "plugin defaults mods")
    _ensure_no_dupes(passive, "plugin defaults passive_mods")

    out: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mods": list(mods),
        "passive_mods": list(passive),
    }

    if "test_mode" in raw:
        if not isinstance(raw.get("test_mode"), bool):
            raise PluginConfigError("plugin defaults test_mode must be bool")
        out["test_mode"] = bool(raw.get("test_mode"))

    for key in _PLUGIN_DEFAULT_STRING_FIELDS:
        if key not in raw:
            continue
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise PluginConfigError(f"plugin defaults {key} must be string")
        if key in {"scheduled_restart_time", "scheduled_update_check_time"}:
            if value and not _is_valid_schedule_time(value):
                raise PluginConfigError(f"plugin defaults {key} must use HH:MM 24-hour format")
        out[key] = value

    for key in _PLUGIN_DEFAULT_INT_FIELDS:
        if key not in raw:
            continue
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            raise PluginConfigError(f"plugin defaults {key} must be int")
        if value < 1 or value > 65535:
            raise PluginConfigError(f"plugin defaults {key} must be between 1 and 65535")
        out[key] = int(value)

    for key in _PLUGIN_DEFAULT_BOOL_FIELDS:
        if key not in raw:
            continue
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, bool):
            raise PluginConfigError(f"plugin defaults {key} must be bool")
        out[key] = bool(value)

    for key, value in raw.items():
        ks = str(key)
        if ks in out or ks.startswith("_"):
            continue
        out[ks] = value

    if path is not None:
        out["_loaded_from"] = str(path)

    return out


def _is_valid_schedule_time(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    parts = text.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return False
    hour = int(parts[0])
    minute = int(parts[1])
    return 0 <= hour <= 23 and 0 <= minute <= 59


def ensure_plugin_defaults_file(cluster_root: str, plugin_name: str) -> Tuple[Path, bool]:
    path = resolve_plugin_defaults_path(cluster_root, plugin_name)
    if path.exists():
        return path, False

    data = _plugin_defaults_fallback()
    write_plugin_defaults_atomic(cluster_root, plugin_name, data)
    return path, True


def load_plugin_defaults_from_path(path: Path | str) -> Dict[str, Any]:
    resolved = Path(path)
    if not resolved.exists():
        return _plugin_defaults_fallback(resolved)

    data = _read_json(resolved)
    return _normalize_plugin_defaults(data, path=resolved)


def load_plugin_defaults(cluster_root: str, plugin_name: str) -> Dict[str, Any]:
    return load_plugin_defaults_from_path(resolve_plugin_defaults_path(cluster_root, plugin_name))


def write_plugin_defaults_atomic(cluster_root: str, plugin_name: str, data: Dict[str, Any]) -> Path:
    normalized = _normalize_plugin_defaults(dict(data or {}))
    persisted = {k: v for k, v in normalized.items() if not str(k).startswith("_")}
    path = plugin_defaults_path(cluster_root, plugin_name)
    _write_json_with_legacy_mirror(path, legacy_plugin_defaults_path(cluster_root, plugin_name), persisted)
    return path


def load_instance_config(cluster_root: str, plugin_name: str, instance_id: str) -> Dict[str, Any]:
    path = resolve_instance_config_path(cluster_root, plugin_name, instance_id)
    if not path.exists():
        raise PluginConfigError("instance config missing")

    data = _read_json(path)

    if data.get("schema_version") != SCHEMA_VERSION:
        raise PluginConfigError("instance schema_version must be 1")

    map_name = data.get("map")
    if not isinstance(map_name, str) or not map_name.strip():
        raise PluginConfigError("instance map must be a non-empty string")

    mods = data.get("mods", [])
    passive = data.get("passive_mods", [])

    if not isinstance(mods, list) or not all(isinstance(x, str) for x in mods):
        raise PluginConfigError("instance mods must be list[str]")

    if not isinstance(passive, list) or not all(isinstance(x, str) for x in passive):
        raise PluginConfigError("instance passive_mods must be list[str]")

    map_mod = data.get("map_mod", None)
    if map_mod is not None and not isinstance(map_mod, str):
        raise PluginConfigError("instance map_mod must be string or null")

    _ensure_no_dupes(mods, "instance mods")
    _ensure_no_dupes(passive, "instance passive_mods")

    ports = data.get("ports")
    if ports is not None:
        if not isinstance(ports, list):
            raise PluginConfigError("instance ports must be list[{name,port,proto}] if present")
        for p in ports:
            if not isinstance(p, dict):
                raise PluginConfigError("instance ports entries must be objects")
            if not isinstance(p.get("name"), str):
                raise PluginConfigError("port name must be string")
            if not isinstance(p.get("port"), int):
                raise PluginConfigError("port port must be int")
            if not isinstance(p.get("proto"), str):
                raise PluginConfigError("port proto must be string")

    return {
        "schema_version": SCHEMA_VERSION,
        "map": map_name,
        "map_mod": map_mod,
        "mods": list(mods),
        "passive_mods": list(passive),
        "ports": ports,
    }


def write_instance_config_atomic(
    cluster_root: str,
    plugin_name: str,
    instance_id: str,
    *,
    map_name: str,
    map_mod: Optional[str],
    mods: List[str],
    passive_mods: List[str],
    ports: List[Dict[str, Any]],
) -> Path:
    if not isinstance(map_name, str) or not map_name.strip():
        raise PluginConfigError("map is required")

    if map_mod is not None and (not isinstance(map_mod, str) or not map_mod.strip()):
        raise PluginConfigError("map_mod must be a non-empty string or null")

    if not isinstance(mods, list) or not all(isinstance(x, str) for x in mods):
        raise PluginConfigError("mods must be list[str]")

    if not isinstance(passive_mods, list) or not all(isinstance(x, str) for x in passive_mods):
        raise PluginConfigError("passive_mods must be list[str]")

    _ensure_no_dupes(mods, "instance mods")
    _ensure_no_dupes(passive_mods, "instance passive_mods")

    data = {
        "schema_version": SCHEMA_VERSION,
        "map": map_name,
        "map_mod": map_mod,
        "mods": list(mods),
        "passive_mods": list(passive_mods),
        "ports": list(ports),
    }

    path = instance_config_path(cluster_root, plugin_name, instance_id)
    _write_json_with_legacy_mirror(path, legacy_instance_config_path(cluster_root, plugin_name, instance_id), data)
    return path


def compute_effective_mods(
    *,
    plugin_defaults_mods: List[str],
    plugin_defaults_passive_mods: List[str],
    instance_mods: List[str],
    instance_passive_mods: List[str],
    map_mod: Optional[str],
) -> Dict[str, List[str]]:
    _ensure_no_dupes(plugin_defaults_mods, "plugin defaults mods")
    _ensure_no_dupes(plugin_defaults_passive_mods, "plugin defaults passive_mods")
    _ensure_no_dupes(instance_mods, "instance mods")
    _ensure_no_dupes(instance_passive_mods, "instance passive_mods")

    if map_mod is not None:
        if map_mod in plugin_defaults_mods:
            raise PluginConfigError("map_mod cannot appear in plugin defaults mods")
        if map_mod in instance_mods:
            raise PluginConfigError("map_mod cannot appear in instance mods")
        if map_mod in plugin_defaults_passive_mods:
            raise PluginConfigError("map_mod cannot appear in plugin defaults passive_mods")
        if map_mod in instance_passive_mods:
            raise PluginConfigError("map_mod cannot appear in instance passive_mods")

    active: List[str] = []
    if map_mod is not None:
        active.append(map_mod)
    active.extend(plugin_defaults_mods)
    active.extend(instance_mods)
    active = _stable_dedupe(active)

    passive: List[str] = []
    passive.extend(plugin_defaults_passive_mods)
    passive.extend(instance_passive_mods)
    passive = _stable_dedupe(passive)

    overlap = set(active) & set(passive)
    if overlap:
        raise PluginConfigError("mods cannot be both active and passive")

    return {
        "active_mods": active,
        "passive_mods": passive,
    }


def _ensure_no_dupes(items: List[str], label: str) -> None:
    seen = set()
    for x in items:
        if x in seen:
            raise PluginConfigError(f"duplicate in {label}: {x}")
        seen.add(x)


def _stable_dedupe(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out




