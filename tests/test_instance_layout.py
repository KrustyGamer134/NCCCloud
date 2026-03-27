import json
from core.instance_layout import get_instance_root, ensure_instance_layout


def test_get_instance_root(tmp_path):
    root = get_instance_root(tmp_path, "ark", "1")
    expected = tmp_path / "plugins" / "ark" / "instances" / "1"
    assert root == expected


def test_ensure_instance_layout_creates_structure(tmp_path):
    result = ensure_instance_layout(tmp_path, "ark", "1")

    instance_root = tmp_path / "plugins" / "ark" / "instances" / "1"

    assert instance_root.exists()
    assert (instance_root / "config").exists()
    assert (instance_root / "data").exists()
    assert (instance_root / "logs").exists()
    assert (instance_root / "backups").exists()

    metadata_file = instance_root / "instance.json"
    assert metadata_file.exists()

    with metadata_file.open("r", encoding="utf-8") as f:
        metadata = json.load(f)

    assert metadata["plugin_name"] == "ark"
    assert metadata["instance_id"] == "1"
    assert metadata["schema_version"] == 1
    assert metadata["install_status"] == "NOT_INSTALLED"

    # Snapshot result is deterministic
    assert result["instance_root"] == str(instance_root)


def test_ensure_instance_layout_idempotent(tmp_path):
    ensure_instance_layout(tmp_path, "ark", "1")
    result_second = ensure_instance_layout(tmp_path, "ark", "1")

    instance_root = tmp_path / "plugins" / "ark" / "instances" / "1"
    metadata_file = instance_root / "instance.json"

    assert metadata_file.exists()

    with metadata_file.open("r", encoding="utf-8") as f:
        metadata = json.load(f)

    # Still correct and not overwritten
    assert metadata["install_status"] == "NOT_INSTALLED"
    assert result_second["instance_root"] == str(instance_root)