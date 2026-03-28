############################################################
# SECTION: Deterministic Instance Layout Utilities
# Purpose:
#     Create and manage deterministic filesystem scaffolding
#     for plugin instances.
#
# Phase:
#     CG-INSTALL-1
#
# Constraints:
#     - No downloads
#     - No installers
#     - No lifecycle interaction
#     - No scheduler interaction
#     - No crash logic changes
#     - No wall-clock timestamps
#     - Deterministic + idempotent
############################################################

from pathlib import Path
import json
import os
import tempfile
from typing import Optional


SCHEMA_VERSION = 1


def _resolve_cluster_config_path(cluster_root: str) -> Path | None:
    base = Path(str(cluster_root))
    candidates = (
        base / "config" / "cluster_config.json",
        base / "cluster_config.json",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _load_cluster_config_fields(cluster_root: str) -> dict:
    path = _resolve_cluster_config_path(cluster_root)
    if path is None:
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _load_plugin_defaults_fields(cluster_root: str, plugin_name: str) -> dict:
    root = Path(str(cluster_root))
    candidates = (
        root / "plugins" / str(plugin_name) / "plugin_defaults.json",
        root / "plugins" / str(plugin_name) / "plugin_config.json",
    )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            raw = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if isinstance(raw, dict):
            return raw
    return {}


def get_instances_root(cluster_root: str, plugin_name: str) -> Path:
    cluster_fields = _load_cluster_config_fields(cluster_root)
    plugin_fields = _load_plugin_defaults_fields(cluster_root, plugin_name)

    gameservers_root = str(cluster_fields.get("gameservers_root") or "").strip()
    cluster_name = str(cluster_fields.get("cluster_name") or "arkSA").strip() or "arkSA"
    install_root = str(plugin_fields.get("install_root") or "").strip()

    if gameservers_root:
        if install_root:
            install_base = Path(install_root)
            if not install_base.is_absolute():
                install_base = Path(gameservers_root) / install_root
            return install_base / "instances"
        return Path(gameservers_root) / cluster_name / "instances"

    return Path(cluster_root) / "plugins" / str(plugin_name) / "instances"


def get_instance_root(cluster_root: str, plugin_name: str, instance_id: str) -> Path:
    """
    Deterministically compute the instance root path.

    Layout:
    Preferred:
    <gameservers_root>/<install_root>/instances/<instance_id>/
    or
    <gameservers_root>/<cluster_name>/instances/<instance_id>/

    Legacy fallback:
    <cluster_root>/plugins/<plugin_name>/instances/<instance_id>/
    """
    return get_instances_root(cluster_root, plugin_name) / str(instance_id)


def read_instance_install_status(cluster_root: str, plugin_name: str, instance_id: str) -> str:
    """
    Deterministic read-only helper.

    Rules:
    - If instance.json missing: NOT_INSTALLED
    - If install_status key missing: NOT_INSTALLED
    - No timestamps
    - No side effects (MUST NOT create layout / files)
    """
    instance_root = get_instance_root(cluster_root, plugin_name, instance_id)
    meta_path = instance_root / "instance.json"

    if not meta_path.exists():
        return "NOT_INSTALLED"

    try:
        with meta_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, json.JSONDecodeError):
        return "NOT_INSTALLED"

    status = meta.get("install_status")
    if not status:
        return "NOT_INSTALLED"

    return str(status)


def ensure_instance_layout(cluster_root: str, plugin_name: str, instance_id: str) -> dict:
    """
    Ensure deterministic instance directory structure exists.

    Idempotent:
    - Safe to call multiple times.
    - Will not overwrite metadata if already present.

    Returns a snapshot dict describing ensured paths.
    """

    instance_root = get_instance_root(cluster_root, plugin_name, instance_id)

    config_dir = instance_root / "config"
    data_dir = instance_root / "data"
    logs_dir = instance_root / "logs"
    backups_dir = instance_root / "backups"

    # Ensure directory tree
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    backups_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = instance_root / "instance.json"

    if not metadata_path.exists():
        metadata = {
            "plugin_name": plugin_name,
            "instance_id": instance_id,
            "schema_version": SCHEMA_VERSION,
            "install_status": "NOT_INSTALLED",
        }

        with metadata_path.open("w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, sort_keys=True)

    return {
        "instance_root": str(instance_root),
        "config_dir": str(config_dir),
        "data_dir": str(data_dir),
        "logs_dir": str(logs_dir),
        "backups_dir": str(backups_dir),
        "metadata_file": str(metadata_path),
    }


def write_instance_install_status(cluster_root: str, plugin_name: str, instance_id: str, install_status: str) -> str:
    """
    Deterministically update instance install_status with atomic replace.

    Rules:
    - Ensures instance layout exists before writing.
    - Uses temp file in target directory + os.replace().
    - No timestamps.
    """
    snapshot = ensure_instance_layout(cluster_root, plugin_name, instance_id)
    metadata_path = Path(snapshot["metadata_file"])

    try:
        with metadata_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)
            if not isinstance(meta, dict):
                meta = {}
    except (OSError, json.JSONDecodeError):
        meta = {}

    meta["plugin_name"] = str(plugin_name)
    meta["instance_id"] = str(instance_id)
    meta["schema_version"] = SCHEMA_VERSION
    meta["install_status"] = str(install_status)

    fd, tmp_path = tempfile.mkstemp(
        prefix="instance_meta_",
        suffix=".tmp",
        dir=str(metadata_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_path, metadata_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return str(install_status)


############################################################
# SECTION: Steam-game install layout resolution
# Purpose:
#     Generic, plugin-agnostic helpers for resolving a
#     managed or legacy install layout from instance/defaults
#     config. All plugin-specific constants are passed as
#     parameters; no game-specific strings live here.
############################################################


def _resolve_install_root(defaults: dict, inst: dict) -> Optional[str]:
    v = inst.get("install_root")
    if v:
        return str(v)
    return None


def _plugin_install_folder(defaults: dict, default_install_folder: str) -> str:
    raw = str(defaults.get("install_folder") or default_install_folder).strip()
    if not raw:
        return default_install_folder
    normalized = raw.replace("/", os.sep).replace("\\", os.sep).rstrip("\\/")
    leaf = os.path.basename(normalized)
    return leaf or default_install_folder


def _managed_install_base(gameservers_root: str, defaults: dict, default_install_folder: str) -> str:
    explicit = str(defaults.get("install_root") or "").strip()
    if explicit:
        if os.path.isabs(explicit):
            return explicit
        return os.path.join(str(gameservers_root), explicit)
    return os.path.join(str(gameservers_root), _plugin_install_folder(defaults, default_install_folder))


def _managed_install_root(
    defaults: dict,
    inst: dict,
    gameservers_root: str,
    map_name: str,
    default_install_folder: str,
) -> Optional[str]:
    if not gameservers_root or not map_name:
        return None

    base_dir = _managed_install_base(gameservers_root, defaults, default_install_folder)
    explicit = str(inst.get("install_root") or "").strip()
    if explicit:
        try:
            if os.path.dirname(os.path.abspath(explicit)) == os.path.abspath(base_dir):
                return explicit
            if gameservers_root and os.path.commonpath([os.path.abspath(explicit), os.path.abspath(gameservers_root)]) == os.path.abspath(gameservers_root):
                return explicit
        except Exception:
            pass
        if os.path.isabs(explicit):
            return None

    prefix = f"{map_name}_"
    next_suffix = 1
    if os.path.isdir(base_dir):
        for name in os.listdir(base_dir):
            full = os.path.join(base_dir, name)
            if not os.path.isdir(full):
                continue
            if not str(name).startswith(prefix):
                continue
            try:
                suffix = int(str(name)[len(prefix):])
            except Exception:
                continue
            if suffix >= next_suffix:
                next_suffix = suffix + 1
    return os.path.join(base_dir, f"{map_name}_{next_suffix}")


def resolve_steam_game_layout(
    defaults: dict,
    inst: dict,
    instance_id: str,
    *,
    default_install_folder: str,
    default_cluster_name: str,
    default_legacy_server_subdir: str = "",
) -> dict:
    map_name = str(inst.get("map") or "").strip()
    gameservers_root = str(inst.get("gameservers_root") or defaults.get("gameservers_root") or "").strip()
    steamcmd_root = str(defaults.get("steamcmd_root") or "").strip()
    cluster_name = str(inst.get("cluster_name") or defaults.get("cluster_name") or default_cluster_name).strip() or default_cluster_name
    legacy_install_root = _resolve_install_root(defaults, inst)
    install_folder = _plugin_install_folder(defaults, default_install_folder)  # noqa: F841

    managed_install_root = _managed_install_root(defaults, inst, gameservers_root, map_name, default_install_folder)

    if managed_install_root:
        steamcmd_dir = steamcmd_root
        install_root = managed_install_root
        return {
            "layout": "canonical",
            "uses_legacy": False,
            "gameservers_root": gameservers_root,
            "steamcmd_root": steamcmd_root or None,
            "cluster_name": cluster_name,
            "map_name": map_name,
            "install_root": install_root,
            "steamcmd_dir": steamcmd_dir or None,
            "cluster_dir": None,
            "map_dir": install_root,
            "server_dir": install_root,
            "logs_dir": os.path.join(install_root, "logs"),
            "tmp_dir": os.path.join(install_root, "tmp"),
            "legacy_install_root": str(legacy_install_root) if legacy_install_root else None,
            "instance_id": str(instance_id),
        }

    if legacy_install_root:
        install_root = str(legacy_install_root)
        legacy_server_dir = (
            os.path.join(install_root, default_legacy_server_subdir)
            if default_legacy_server_subdir
            else install_root
        )
        return {
            "layout": "legacy_install_root",
            "uses_legacy": True,
            "gameservers_root": gameservers_root or None,
            "steamcmd_root": steamcmd_root or None,
            "cluster_name": cluster_name,
            "map_name": map_name or None,
            "install_root": install_root,
            "steamcmd_dir": steamcmd_root or None,
            "cluster_dir": None,
            "map_dir": install_root,
            "server_dir": legacy_server_dir,
            "logs_dir": os.path.join(install_root, "logs"),
            "tmp_dir": os.path.join(install_root, "tmp"),
            "legacy_install_root": install_root,
            "instance_id": str(instance_id),
        }

    return {
        "layout": "missing",
        "uses_legacy": False,
        "gameservers_root": gameservers_root or None,
        "steamcmd_root": steamcmd_root or None,
        "cluster_name": cluster_name,
        "map_name": map_name or None,
        "install_root": None,
        "steamcmd_dir": steamcmd_root or None,
        "cluster_dir": None,
        "map_dir": None,
        "server_dir": None,
        "logs_dir": None,
        "tmp_dir": None,
        "legacy_install_root": None,
        "instance_id": str(instance_id),
    }


def resolve_steam_game_master_layout(
    defaults: dict,
    *,
    plugin_name: str,
    default_install_folder: str,
) -> dict:
    gameservers_root = str(defaults.get("gameservers_root") or "").strip()
    steamcmd_root = str(defaults.get("steamcmd_root") or "").strip()
    configured_root = str(defaults.get("master_install_root") or "").strip()

    install_root = None
    if configured_root:
        if os.path.isabs(configured_root):
            install_root = configured_root
        elif gameservers_root:
            install_root = os.path.join(gameservers_root, configured_root)
    elif gameservers_root:
        install_root = os.path.join(
            gameservers_root,
            ".ncc",
            "masters",
            str(plugin_name),
            default_install_folder,
        )

    if not install_root:
        return {
            "layout": "missing_master",
            "is_master": True,
            "plugin_name": str(plugin_name),
            "gameservers_root": gameservers_root or None,
            "steamcmd_root": steamcmd_root or None,
            "install_root": None,
            "server_dir": None,
            "logs_dir": None,
            "tmp_dir": None,
            "steamcmd_dir": steamcmd_root or None,
        }

    return {
        "layout": "master",
        "is_master": True,
        "plugin_name": str(plugin_name),
        "gameservers_root": gameservers_root or None,
        "steamcmd_root": steamcmd_root or None,
        "install_root": install_root,
        "server_dir": install_root,
        "logs_dir": os.path.join(install_root, "logs"),
        "tmp_dir": os.path.join(install_root, "tmp"),
        "steamcmd_dir": steamcmd_root or None,
    }
