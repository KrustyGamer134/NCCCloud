############################################################
# SECTION: Deterministic Stub Installer
# Purpose:
#     Install-on-first-run state transitions ONLY.
#     No real installation occurs in this phase.
# Phase:
#     CG-FIRST-RUN-INSTALL-1
# Constraints:
#     - No network / downloads
#     - No subprocess / SteamCMD
#     - No wall-clock timestamps
#     - No threads / async
#     - Deterministic + synchronous
############################################################

import json
from pathlib import Path

from core.instance_layout import get_instance_root, ensure_instance_layout


VALID_INSTALL_STATUSES = {
    "NOT_INSTALLED",
    "INSTALLING",
    "INSTALLED",
    "FAILED",
}


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def ensure_installed(cluster_root: str, plugin_name: str, instance_id: str) -> dict:
    """
    Deterministic stub installer.

    Behavior:
    - Ensures layout exists (idempotent).
    - Reads instance.json
    - If INSTALLED: no-op
    - If NOT_INSTALLED or FAILED: transitions INSTALLING -> INSTALLED immediately
    - If force_install_fail is true: transitions INSTALLING -> FAILED
    - No external side effects beyond instance.json
    """
    # Ensure CG-INSTALL-1 layout exists (idempotent)
    ensure_instance_layout(cluster_root, plugin_name, instance_id)

    instance_root = get_instance_root(cluster_root, plugin_name, instance_id)
    meta_path = instance_root / "instance.json"

    meta = _read_json(meta_path)
    if meta is None:
        # Should not happen due to ensure_instance_layout, but keep deterministic fallback
        meta = {
            "plugin_name": plugin_name,
            "instance_id": instance_id,
            "schema_version": 1,
            "install_status": "NOT_INSTALLED",
        }
        _write_json(meta_path, meta)

    status = meta.get("install_status", "NOT_INSTALLED")

    # Normalize unknown status deterministically
    if status not in VALID_INSTALL_STATUSES:
        status = "NOT_INSTALLED"

    if status == "INSTALLED":
        return {"status": "INSTALLED"}

    # Test-only deterministic failure control (inactive unless explicitly set)
    force_fail = bool(meta.get("force_install_fail", False))

    # Transition to INSTALLING
    meta["install_status"] = "INSTALLING"
    _write_json(meta_path, meta)

    if force_fail:
        meta["install_status"] = "FAILED"
        _write_json(meta_path, meta)
        return {"status": "FAILED", "message": "Forced install failure"}

    # Stub: immediately succeed
    meta["install_status"] = "INSTALLED"
    _write_json(meta_path, meta)

    return {"status": "INSTALLED"}