import json
from pathlib import Path

from core.instance_layout import get_instance_root, ensure_instance_layout
from core.installer import ensure_installed


def test_ensure_installed_transitions_not_installed_to_installed(tmp_path: Path):
    cluster_root = str(tmp_path)

    # Ensure layout + metadata exists (starts as NOT_INSTALLED)
    ensure_instance_layout(cluster_root, "ark", "1")

    instance_root = get_instance_root(cluster_root, "ark", "1")
    meta_path = instance_root / "instance.json"

    with meta_path.open("r", encoding="utf-8") as f:
        meta = json.load(f)

    assert meta["install_status"] == "NOT_INSTALLED"

    # Run stub installer
    result = ensure_installed(cluster_root, "ark", "1")
    assert result["status"] == "INSTALLED"

    # Verify metadata updated
    with meta_path.open("r", encoding="utf-8") as f:
        meta2 = json.load(f)

    assert meta2["install_status"] == "INSTALLED"


def test_ensure_installed_idempotent_when_installed(tmp_path: Path):
    cluster_root = str(tmp_path)

    ensure_instance_layout(cluster_root, "ark", "1")
    ensure_installed(cluster_root, "ark", "1")

    # Run again: should no-op deterministically
    result = ensure_installed(cluster_root, "ark", "1")
    assert result["status"] == "INSTALLED"