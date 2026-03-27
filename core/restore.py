############################################################
# SECTION: Manual Selective Restore (STOPPED-Only)
# Purpose:
#     Restore selected files from a backup zip into ARK SavedArks.
#
# Phase:
#     CG-RESTORE-1
#
# Constraints:
#     - STOPPED-only gate enforced by AdminAPI caller
#     - No restore-all implicitly (explicit selector required)
#     - Deterministic selection + ordering
#     - No threads/async/network/subprocess
#     - Merge-only: overwrite restored files, never delete others
############################################################

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import json
import zipfile


PLAYER_INDEX_NAME = "player_index.json"
ALLOWED_SUFFIXES = (".ark", ".arkprofile", ".arktribe")


@dataclass(frozen=True)
class RestoreSelection:
    kind: str  # "mode" | "player-name" | "files"
    value: str | None
    files: list[str]


def _is_safe_zip_entry(name: str) -> bool:
    # Reject absolute paths
    if name.startswith("/") or name.startswith("\\"):
        return False

    # Reject Windows drive-like paths (C:\..., D:..., etc.)
    if ":" in name.split("/")[0] or ":" in name.split("\\")[0]:
        return False

    p = PurePosixPath(name)

    # Reject traversal
    if any(part == ".." for part in p.parts):
        return False

    # Reject empty / directory entries
    if not name or name.endswith("/"):
        return False

    # Allowed file types only
    if not any(name.endswith(suf) for suf in ALLOWED_SUFFIXES):
        return False

    return True


def safe_list_zip_entries(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
    # Deterministic order
    return sorted(names)


def _load_player_index(index_path: Path) -> list[dict]:
    if not index_path.exists():
        raise ValueError("player_index.json missing")

    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError("player_index.json invalid JSON")

    if int(raw.get("schema_version", 0)) != 1:
        raise ValueError("player_index.json schema_version must be 1")

    players = raw.get("players")
    if not isinstance(players, list):
        raise ValueError("player_index.json players must be a list")

    out: list[dict] = []
    for item in players:
        if not isinstance(item, dict):
            continue
        pid = item.get("playerID")
        name = item.get("name")
        if isinstance(pid, str) and isinstance(name, str) and pid and name:
            out.append({"playerID": pid, "name": name})

    return out


def resolve_selection(
    *,
    zip_entries: list[str],
    backup_root: Path,
    plugin_name: str,
    instance_id: str,
    selector_player_name: str | None,
    selector_mode: str | None,
    selector_files: list[str] | None,
) -> RestoreSelection:
    # Exactly one selector required
    provided = [
        selector_player_name is not None,
        selector_mode is not None,
        selector_files is not None,
    ]
    if sum(1 for x in provided if x) != 1:
        raise ValueError("Exactly one selector is required: --player-name OR --mode OR --files")

    zip_set = set(zip_entries)

    if selector_mode is not None:
        mode = str(selector_mode)
        if mode == "world":
            wanted = [n for n in zip_entries if n.endswith(".ark")]
        elif mode == "players":
            wanted = [n for n in zip_entries if n.endswith(".arkprofile")]
        elif mode == "tribes":
            wanted = [n for n in zip_entries if n.endswith(".arktribe")]
        else:
            raise ValueError("Invalid --mode (must be world|players|tribes)")

        wanted = [n for n in wanted if _is_safe_zip_entry(n)]
        return RestoreSelection(kind="mode", value=mode, files=wanted)

    if selector_files is not None:
        req = [str(x) for x in selector_files]
        if not req:
            raise ValueError("--files requires at least 1 zip entry")

        missing = [n for n in req if n not in zip_set]
        if missing:
            raise ValueError(f"Requested zip entries not found: {missing}")

        for n in req:
            if not _is_safe_zip_entry(n):
                raise ValueError(f"Unsafe or disallowed zip entry: {n}")

        # Deterministic order
        req = sorted(req)
        return RestoreSelection(kind="files", value=None, files=req)

    # selector_player_name
    player_name = str(selector_player_name)
    index_path = backup_root / str(plugin_name) / str(instance_id) / PLAYER_INDEX_NAME
    players = _load_player_index(index_path)

    matches = [p for p in players if p.get("name") == player_name]
    if not matches:
        raise ValueError("Player not found in player_index.json")
    if len(matches) > 1:
        raise ValueError("Player name is not unique in player_index.json")

    player_id = matches[0]["playerID"]
    target = f"{player_id}.arkprofile"

    if target not in zip_set:
        raise ValueError("Selected player profile not found in backup zip")

    if not _is_safe_zip_entry(target):
        raise ValueError("Selected player profile zip entry is unsafe")

    return RestoreSelection(kind="player-name", value=player_name, files=[target])


def _safe_destination_path(target_dir: Path, zip_name: str) -> Path:
    # zip_name uses / separators
    rel = PurePosixPath(zip_name)
    # Convert to OS path under target_dir
    out = target_dir.joinpath(*rel.parts)
    # Enforce containment after normalization
    target_resolved = target_dir.resolve()
    out_resolved = out.resolve()
    if target_resolved != out_resolved and target_resolved not in out_resolved.parents:
        raise ValueError(f"Unsafe destination path for zip entry: {zip_name}")
    return out


def perform_restore(
    *,
    cluster_root: str,
    plugin_name: str,
    instance_id: str,
    zip_path: Path,
    selection: RestoreSelection,
) -> dict:
    from core.instance_layout import get_instance_root
    from core.backup import SAVEDARKS_REL

    instance_root = get_instance_root(cluster_root, plugin_name, instance_id)
    target_dir = instance_root / SAVEDARKS_REL
    target_dir.mkdir(parents=True, exist_ok=True)

    restored: list[str] = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        for name in selection.files:
            if name not in zf.namelist():
                raise ValueError(f"Zip entry missing at restore time: {name}")
            if not _is_safe_zip_entry(name):
                raise ValueError(f"Unsafe or disallowed zip entry: {name}")

            dest_path = _safe_destination_path(target_dir, name)
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            with zf.open(name, "r") as src, dest_path.open("wb") as dst:
                dst.write(src.read())

            restored.append(name)

    restored = sorted(restored)
    return {
        "backup_path": str(zip_path),
        "files_restored_count": int(len(restored)),
        "restored_entries": restored,
        "selector_kind": selection.kind,
        "selector_value": selection.value,
    }