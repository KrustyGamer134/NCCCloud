############################################################
# SECTION: Deterministic Manual Delta Backups
# Purpose:
#     Create delta-only backups of ARK SavedArks files to a
#     user-defined backup root using a manifest (no hashing).
#
# Phase:
#     CG-BACKUP-1
#
# Constraints:
#     - No network/subprocess/SteamCMD
#     - No threads/async/timers
#     - No scheduler changes
#     - No lifecycle logic changes
#     - Deterministic selection logic based on manifest
#     - Wall-clock allowed for filename only
############################################################

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import re
import zipfile
from datetime import datetime


SAVEDARKS_REL = Path("data") / "ShooterGame" / "Saved" / "SavedArks"
MANIFEST_NAME = "backup_manifest.json"


@dataclass(frozen=True)
class ManifestEntry:
    size_bytes: int
    mtime_ns: int


def find_savedarks_dir(cluster_root: str, plugin_name: str, instance_id: str) -> Path:
    from core.instance_layout import get_instance_root

    instance_root = get_instance_root(cluster_root, plugin_name, instance_id)
    return instance_root / SAVEDARKS_REL


def load_manifest(manifest_path: Path) -> dict[str, ManifestEntry]:
    if not manifest_path.exists():
        return {}

    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    out: dict[str, ManifestEntry] = {}
    files = raw.get("files", {})
    if isinstance(files, dict):
        for rel, meta in files.items():
            if not isinstance(rel, str) or not isinstance(meta, dict):
                continue
            try:
                size = int(meta.get("size_bytes", 0))
                mtime = int(meta.get("mtime_ns", 0))
            except (TypeError, ValueError):
                continue
            out[rel] = ManifestEntry(size_bytes=size, mtime_ns=mtime)

    return out


def save_manifest(manifest_path: Path, entries: dict[str, ManifestEntry]) -> None:
    payload = {
        "schema_version": 1,
        "files": {
            rel: {"size_bytes": int(e.size_bytes), "mtime_ns": int(e.mtime_ns)}
            for rel, e in sorted(entries.items(), key=lambda kv: kv[0])
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _iter_candidate_files(savedarks_dir: Path) -> list[Path]:
    # Locked: backups must contain map/world (*.ark), player (*.arkprofile), tribe (*.arktribe)
    patterns = ("*.ark", "*.arkprofile", "*.arktribe")
    found: list[Path] = []
    for pat in patterns:
        found.extend(sorted(savedarks_dir.glob(pat)))
    # Deterministic order by relative path string
    found = sorted(found, key=lambda p: str(p.relative_to(savedarks_dir)).replace("\\", "/"))
    return found


def compute_delta(savedarks_dir: Path, manifest: dict[str, ManifestEntry]) -> list[Path]:
    delta: list[Path] = []
    for path in _iter_candidate_files(savedarks_dir):
        try:
            st = path.stat()
        except OSError:
            continue

        rel = str(path.relative_to(savedarks_dir)).replace("\\", "/")
        prev = manifest.get(rel)
        if prev and int(prev.size_bytes) == int(st.st_size) and int(prev.mtime_ns) == int(st.st_mtime_ns):
            continue

        delta.append(path)

    return delta


def derive_map_name_from_savedarks(savedarks_dir: Path, instance_id_fallback: str) -> str:
    # Deterministic derivation from .ark filenames in SavedArks.
    # Use base prefix before the first _DD.MM.YYYY_... if present
    # else fallback to instance_id.
    ark_files = sorted(savedarks_dir.glob("*.ark"), key=lambda p: p.name)
    if not ark_files:
        return str(instance_id_fallback)

    rx = re.compile(r"^(?P<prefix>.+?)_\d{2}\.\d{2}\.\d{4}_", re.IGNORECASE)
    prefixes: set[str] = set()

    for p in ark_files:
        stem = p.stem
        m = rx.match(stem)
        if m:
            pref = m.group("prefix").strip()
            if pref:
                prefixes.add(pref)

    if len(prefixes) == 1:
        return next(iter(prefixes))

    return str(instance_id_fallback)


def _timestamp_for_filename() -> str:
    # Wall-clock allowed for filename only.
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def create_backup_zip(
    *,
    savedarks_dir: Path,
    backup_dest_dir: Path,
    instance_id_fallback: str,
    manifest_path: Path,
) -> dict:
    if not savedarks_dir.exists() or not savedarks_dir.is_dir():
        raise ValueError(f"SavedArks directory not found: {savedarks_dir}")

    manifest = load_manifest(manifest_path)
    delta_files = compute_delta(savedarks_dir, manifest)

    map_name = derive_map_name_from_savedarks(savedarks_dir, instance_id_fallback)
    zip_name = f"{map_name}_{_timestamp_for_filename()}.zip"
    backup_dest_dir.mkdir(parents=True, exist_ok=True)
    zip_path = backup_dest_dir / zip_name

    bytes_total = 0
    for p in delta_files:
        try:
            bytes_total += int(p.stat().st_size)
        except OSError:
            pass

    # Create zip (only delta)
    # If delta is empty: still produce a valid zip with 0 files.
    try:
        with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in delta_files:
                rel = str(p.relative_to(savedarks_dir)).replace("\\", "/")
                zf.write(p, arcname=rel)
    except Exception:
        # Do not update manifest on failure
        raise

    # Update manifest only after successful zip creation
    for p in delta_files:
        try:
            st = p.stat()
        except OSError:
            continue
        rel = str(p.relative_to(savedarks_dir)).replace("\\", "/")
        manifest[rel] = ManifestEntry(size_bytes=int(st.st_size), mtime_ns=int(st.st_mtime_ns))

    save_manifest(manifest_path, manifest)

    return {
        "backup_path": str(zip_path),
        "files_included_count": int(len(delta_files)),
        "bytes_included_total": int(bytes_total),
        "map_name": str(map_name),
        "manifest_path": str(manifest_path),
    }