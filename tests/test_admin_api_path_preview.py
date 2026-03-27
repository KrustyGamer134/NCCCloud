import json
from pathlib import Path

from core.admin_api import AdminAPI


class _StubOrchestrator:
    def __init__(self, cluster_root: Path):
        self._cluster_root = str(cluster_root)
        self.calls = []

    def send_action(self, plugin_name, action, payload=None):
        self.calls.append((str(plugin_name), str(action), dict(payload or {})))
        return {"status": "success", "data": {"plugin": str(plugin_name), "action": str(action), "payload": dict(payload or {})}}


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_instance_path_preview_canonical(tmp_path):
    api = AdminAPI(_StubOrchestrator(tmp_path))

    gameservers_root = tmp_path / "GameServers"
    api.set_cluster_config_fields({"gameservers_root": str(gameservers_root), "cluster_name": "arkSA"})
    _write_json(
        tmp_path / "plugins" / "ark" / "instances" / "10" / "config" / "plugin_instance_config.json",
        {"schema_version": 1, "map": "theisland_wp"},
    )

    resp = api.get_instance_path_preview("ark", "10")
    assert resp["status"] == "success"
    data = resp["data"]
    assert data["map_name"] == "theisland_wp"
    assert data["using_legacy_install_root"] is False
    assert data["canonical"]["server_dir"] == str(gameservers_root / "ArkSA" / "theisland_wp_1")
    assert data["legacy"]["install_root"] is None


def test_instance_path_preview_uses_plugin_install_root_relative_to_gameservers_root(tmp_path):
    api = AdminAPI(_StubOrchestrator(tmp_path))

    gameservers_root = tmp_path / "GameServers"
    api.set_cluster_config_fields({"gameservers_root": str(gameservers_root), "cluster_name": "arkSA"})
    _write_json(
        tmp_path / "plugins" / "ark" / "plugin_config.json",
        {"schema_version": 1, "install_root": "BriansPlayground"},
    )
    _write_json(
        tmp_path / "plugins" / "ark" / "instances" / "10" / "config" / "plugin_instance_config.json",
        {"schema_version": 1, "map": "theisland_wp"},
    )

    resp = api.get_instance_path_preview("ark", "10")

    assert resp["status"] == "success"
    data = resp["data"]
    assert data["canonical"]["server_dir"] == str(gameservers_root / "BriansPlayground" / "theisland_wp_1")


def test_instance_path_preview_legacy_when_canonical_missing(tmp_path):
    api = AdminAPI(_StubOrchestrator(tmp_path))

    _write_json(
        tmp_path / "plugins" / "ark" / "instances" / "10" / "config" / "plugin_instance_config.json",
        {"schema_version": 1, "install_root": r"C:\LegacyArk"},
    )

    resp = api.get_instance_path_preview("ark", "10")
    assert resp["status"] == "success"
    data = resp["data"]
    assert data["using_legacy_install_root"] is True
    assert data["legacy"]["install_root"] == r"C:\LegacyArk"
    assert data["legacy"]["server_dir"] == r"C:\LegacyArk\asa_server"
    assert any("canonical inputs missing" in w for w in data["warnings"])


def test_instance_path_preview_treats_absolute_install_root_under_gameservers_root_as_canonical(tmp_path):
    api = AdminAPI(_StubOrchestrator(tmp_path))

    gameservers_root = tmp_path / "GameServers"
    api.set_cluster_config_fields({"gameservers_root": str(gameservers_root), "cluster_name": "arkSA"})
    imported_root = gameservers_root / "ImportedServers" / "brianragnarok_wp"
    _write_json(
        tmp_path / "plugins" / "ark" / "instances" / "10" / "config" / "plugin_instance_config.json",
        {"schema_version": 1, "map": "brianragnarok_wp", "install_root": str(imported_root)},
    )

    resp = api.get_instance_path_preview("ark", "10")

    assert resp["status"] == "success"
    data = resp["data"]
    assert data["using_legacy_install_root"] is False
    assert data["canonical"]["server_dir"] == str(imported_root)


def test_get_log_tail_uses_same_cluster_aware_logs_root_as_path_preview(tmp_path):
    api = AdminAPI(_StubOrchestrator(tmp_path))

    gameservers_root = tmp_path / "GameServers"
    api.set_cluster_config_fields({"gameservers_root": str(gameservers_root), "cluster_name": "arkSA"})
    managed_root = gameservers_root / "ArkSA" / "theisland_wp_1"
    _write_json(
        tmp_path / "plugins" / "ark" / "instances" / "10" / "config" / "plugin_instance_config.json",
        {"schema_version": 1, "map": "theisland_wp", "install_root": str(managed_root)},
    )
    log_path = managed_root / "logs" / "steamcmd_install.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("line1\nline2\n", encoding="utf-8")

    preview = api.get_instance_path_preview("ark", "10")
    tail = api.get_log_tail("ark", "10", "steamcmd_install", last_lines=1)

    assert preview["status"] == "success"
    assert tail["status"] == "success"
    assert tail["data"]["path"] == str(log_path)
    assert tail["data"]["lines"] == ["line2"]
    assert tail["data"]["path"] == str(Path(preview["data"]["canonical"]["logs_dir"]) / "steamcmd_install.log")


def test_adminapi_runtime_status_wrapper_calls_send_action(tmp_path):
    orch = _StubOrchestrator(tmp_path)
    api = AdminAPI(orch)

    resp = api.inspect_runtime_status("ark", "10")
    assert resp["status"] == "success"
    assert ("ark", "runtime_status", {"instance_id": "10"}) in orch.calls

