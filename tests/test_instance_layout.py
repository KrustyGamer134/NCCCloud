import json
from pathlib import Path
from core.instance_layout import get_instance_root, get_instances_root, ensure_instance_layout


def _write_config(tmp_path):
    gameservers_root = tmp_path / "GameServers"
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "cluster_config.json").write_text(
        json.dumps(
            {
                "gameservers_root": str(gameservers_root),
                "cluster_name": "arkSA",
            }
        ),
        encoding="utf-8",
    )
    plugin_dir = tmp_path / "plugins" / "ark"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin_config.json").write_text(
        json.dumps(
            {
                "install_root": "arkSA",
            }
        ),
        encoding="utf-8",
    )


def test_get_instance_root(tmp_path):
    _write_config(tmp_path)
    root = get_instance_root(tmp_path, "ark", "1")
    expected = tmp_path / "GameServers" / "arkSA" / "instances" / "1"
    assert root == expected


def test_ensure_instance_layout_creates_structure(tmp_path):
    _write_config(tmp_path)
    result = ensure_instance_layout(tmp_path, "ark", "1")

    instance_root = tmp_path / "GameServers" / "arkSA" / "instances" / "1"

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
    _write_config(tmp_path)
    ensure_instance_layout(tmp_path, "ark", "1")
    result_second = ensure_instance_layout(tmp_path, "ark", "1")

    instance_root = tmp_path / "GameServers" / "arkSA" / "instances" / "1"
    metadata_file = instance_root / "instance.json"

    assert metadata_file.exists()

    with metadata_file.open("r", encoding="utf-8") as f:
        metadata = json.load(f)

    # Still correct and not overwritten
    assert metadata["install_status"] == "NOT_INSTALLED"
    assert result_second["instance_root"] == str(instance_root)


def test_get_instance_root_uses_gameservers_root_and_install_root(tmp_path):
    _write_config(tmp_path)

    root = get_instance_root(tmp_path, "ark", "1")

    assert root == tmp_path / "GameServers" / "arkSA" / "instances" / "1"


def test_ensure_instance_layout_uses_gameservers_root_and_install_root(tmp_path):
    _write_config(tmp_path)

    result = ensure_instance_layout(tmp_path, "ark", "1")
    instance_root = tmp_path / "GameServers" / "arkSA" / "instances" / "1"

    assert instance_root.exists()
    assert (instance_root / "instance.json").exists()
    assert result["instance_root"] == str(instance_root)


def test_get_instances_root_falls_back_to_cluster_name_when_plugin_install_root_missing(tmp_path):
    gameservers_root = tmp_path / "GameServers"
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "cluster_config.json").write_text(
        json.dumps(
            {
                "gameservers_root": str(gameservers_root),
                "cluster_name": "arkSA",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "plugins" / "ark").mkdir(parents=True, exist_ok=True)

    root = get_instances_root(tmp_path, "ark")

    assert root == gameservers_root / "arkSA" / "instances"
