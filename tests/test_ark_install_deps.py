import json
from pathlib import Path

from core.plugin_handler import PluginHandler


def _make_handler(tmp_path, cluster_root=None, defaults=None):
    real_ark = Path(__file__).resolve().parents[1] / "plugins" / "ark"
    with open(real_ark / "plugin.json", encoding="utf-8") as f:
        plugin_json = json.load(f)
    plugin_dir = tmp_path / "plugins" / "ark"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    if defaults is not None:
        (plugin_dir / "plugin_config.json").write_text(
            json.dumps({"schema_version": 1, **defaults}), encoding="utf-8"
        )
    return PluginHandler(
        plugin_json=plugin_json,
        plugin_dir=str(plugin_dir),
        cluster_root=str(cluster_root or tmp_path),
    )


def _write_instance_config(tmp_path, instance_id, config):
    path = (
        tmp_path
        / "plugins"
        / "ark"
        / "instances"
        / instance_id
        / "config"
        / "plugin_instance_config.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config), encoding="utf-8")


def test_install_deps_creates_canonical_dirs_for_map_instance(tmp_path):
    gameservers_root = tmp_path / "GameServers"
    handler = _make_handler(tmp_path, defaults={"gameservers_root": str(gameservers_root)})
    _write_instance_config(tmp_path, "10", {"map": "theisland_wp"})

    resp = handler.handle("install_deps", {"instance_id": "10"})

    assert resp["status"] == "success"
    assert resp["data"]["ok"] is True

    map_root = gameservers_root / "ArkSA" / "theisland_wp_1"
    assert map_root.is_dir()
    assert (map_root / "logs").is_dir()
    assert (map_root / "tmp").is_dir()


def test_install_deps_canonical_server_dir_equals_install_root(tmp_path):
    gameservers_root = tmp_path / "GameServers"
    handler = _make_handler(tmp_path, defaults={"gameservers_root": str(gameservers_root)})
    _write_instance_config(tmp_path, "10", {"map": "theisland_wp"})

    resp = handler.handle("install_deps", {"instance_id": "10"})

    # In canonical layout, server_dir == map_dir == install_root
    created = resp["data"]["created"]
    assert created.get("server_dir") == created.get("map_dir")
    assert created.get("server_dir") == str(gameservers_root / "ArkSA" / "theisland_wp_1")


def test_install_deps_legacy_install_root_creates_server_subdir(tmp_path):
    install_root = tmp_path / "legacy_install"
    handler = _make_handler(tmp_path)
    _write_instance_config(tmp_path, "10", {"install_root": str(install_root)})

    resp = handler.handle("install_deps", {"instance_id": "10"})

    assert resp["status"] == "success"
    assert resp["data"]["ok"] is True
    # Legacy layout: server_dir = install_root/server (not asa_server)
    assert (install_root / "server").is_dir()
    assert (install_root / "logs").is_dir()
    assert (install_root / "tmp").is_dir()


def test_install_deps_legacy_server_subdir_is_server_not_asa_server(tmp_path):
    install_root = tmp_path / "legacy_install"
    handler = _make_handler(tmp_path)
    _write_instance_config(tmp_path, "10", {"install_root": str(install_root)})

    resp = handler.handle("install_deps", {"instance_id": "10"})

    created = resp["data"]["created"]
    assert created.get("server_dir") == str(install_root / "server")
    # Explicitly verify the old path is NOT used
    assert not (install_root / "asa_server").exists()


def test_install_deps_uses_next_map_suffix_when_existing_dir_present(tmp_path):
    gameservers_root = tmp_path / "GameServers"
    # Pre-create theisland_wp_1 to force suffix to 2
    (gameservers_root / "ArkSA" / "theisland_wp_1").mkdir(parents=True, exist_ok=True)

    handler = _make_handler(tmp_path, defaults={"gameservers_root": str(gameservers_root)})
    _write_instance_config(tmp_path, "10", {"map": "theisland_wp"})

    resp = handler.handle("install_deps", {"instance_id": "10"})

    assert resp["status"] == "success"
    created = resp["data"]["created"]
    assert "theisland_wp_2" in created.get("server_dir", "")


def test_install_deps_response_structure(tmp_path):
    handler = _make_handler(tmp_path)
    _write_instance_config(tmp_path, "10", {"map": "theisland_wp"})

    resp = handler.handle("install_deps", {"instance_id": "10"})

    assert resp["status"] == "success"
    data = resp["data"]
    assert data["ok"] is True
    assert isinstance(data["warnings"], list)
    assert isinstance(data["errors"], list)
    assert isinstance(data["created"], dict)
    assert data["errors"] == []


def test_install_deps_cluster_root_injection_succeeds_without_gameservers_root(tmp_path):
    # No gameservers_root, no install_root → cluster_root injection kicks in
    handler = _make_handler(tmp_path)
    _write_instance_config(tmp_path, "10", {})

    resp = handler.handle("install_deps", {"instance_id": "10"})

    # Cluster root injection always provides a path → success
    assert resp["status"] == "success"
    assert resp["data"]["ok"] is True
