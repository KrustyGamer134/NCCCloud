import json
from pathlib import Path

from core.admin_api import AdminAPI
from core.orchestrator import Orchestrator
from core.state_manager import StateManager


class _StubOrchestrator:
    def __init__(self, cluster_root: Path):
        self._cluster_root = str(cluster_root)
        self.mark_dirty_calls = 0
        self.mark_instance_dirty_calls = []
        self.mark_plugin_dirty_calls = []
        self.invalidate_runtime_calls = []
        self.clear_instance_config_calls = []
        self.sync_instance_ini_calls = []

    def get_app_setup_report(self):
        return {
            "status": "missing",
            "results": [
                {"id": "gameservers_root", "label": "GameServers Root", "status": "missing", "details": "gameservers_root is not configured."},
                {"id": "steamcmd_root", "label": "SteamCMD Root", "status": "missing", "details": "steamcmd_root is not configured."},
            ],
        }

    def _mark_app_setup_report_dirty(self):
        self.mark_dirty_calls += 1

    def _mark_instance_readiness_dirty(self, plugin_name=None, instance_id=None):
        self.mark_instance_dirty_calls.append((plugin_name, instance_id))

    def _mark_plugin_readiness_dirty(self, plugin_name=None):
        self.mark_plugin_dirty_calls.append(plugin_name)

    def _invalidate_runtime_summary(self, plugin_name=None, instance_id=None):
        self.invalidate_runtime_calls.append((plugin_name, instance_id))

    def _iter_instance_keys(self, plugin_name=None):
        items = [("ark", "10"), ("ark", "20"), ("e2e_harness", "1")]
        if plugin_name is None:
            return list(items)
        return [item for item in items if item[0] == str(plugin_name)]

    def _plugins_for_dependency(self, dep_id):
        if str(dep_id) == "steamcmd":
            return ["ark"]
        return []

    def clear_instance_config_fields(self, plugin_name, instance_id, field_names):
        self.clear_instance_config_calls.append((str(plugin_name), str(instance_id), list(field_names or [])))
        return {"status": "success", "data": {"ok": True}}

    def sync_instance_ini_fields(self, plugin_name, instance_id, field_names):
        self.sync_instance_ini_calls.append((str(plugin_name), str(instance_id), list(field_names or [])))
        return {"status": "success", "data": {"ok": True}}


def test_adminapi_cluster_settings_get_set_persists(tmp_path):
    orch = _StubOrchestrator(tmp_path)
    api = AdminAPI(orch)

    got = api.get_cluster_config_fields(["gameservers_root", "cluster_name", "steamcmd_root"])
    assert got["status"] == "success"
    assert got["data"]["fields"]["gameservers_root"] == ""
    assert got["data"]["fields"]["cluster_name"] == "arkSA"
    assert got["data"]["fields"]["steamcmd_root"] == ""

    set_resp = api.set_cluster_config_fields(
        {
            "gameservers_root": r"D:\GameServers",
            "cluster_name": "arkProd",
            "steamcmd_root": r"D:\SteamCMD",
        }
    )
    assert set_resp["status"] == "success"
    assert set_resp["data"]["fields"]["gameservers_root"] == r"D:\GameServers"
    assert set_resp["data"]["fields"]["cluster_name"] == "arkProd"
    assert set_resp["data"]["fields"]["steamcmd_root"] == r"D:\SteamCMD"
    assert any("cluster_name changed" in w for w in set_resp["data"]["warnings"])

    cfg_path = tmp_path / "cluster_config.json"
    assert cfg_path.is_file()
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert raw["gameservers_root"] == r"D:\GameServers"
    assert raw["cluster_name"] == "arkProd"
    assert raw["steamcmd_root"] == r"D:\SteamCMD"

    got2 = api.get_cluster_config_fields(["gameservers_root", "cluster_name", "steamcmd_root"])
    assert got2["status"] == "success"
    assert got2["data"]["fields"]["gameservers_root"] == r"D:\GameServers"
    assert got2["data"]["fields"]["cluster_name"] == "arkProd"
    assert got2["data"]["fields"]["steamcmd_root"] == r"D:\SteamCMD"
    assert orch.mark_dirty_calls == 1


def test_adminapi_cluster_settings_only_marks_app_setup_dirty_for_relevant_changes(tmp_path):
    orch = _StubOrchestrator(tmp_path)
    api = AdminAPI(orch)

    resp = api.set_cluster_config_fields({"cluster_name": "arkProd"})

    assert resp["status"] == "success"
    assert orch.mark_dirty_calls == 0


def test_adminapi_cluster_settings_marks_instance_readiness_dirty_when_gameservers_root_changes(tmp_path):
    orch = _StubOrchestrator(tmp_path)
    api = AdminAPI(orch)

    resp = api.set_cluster_config_fields({"gameservers_root": r"D:\GameServers"})

    assert resp["status"] == "success"
    assert orch.mark_instance_dirty_calls == [("ark", "10"), ("ark", "20"), ("e2e_harness", "1")]
    assert orch.mark_plugin_dirty_calls == []
    assert orch.invalidate_runtime_calls == [(None, None)]


def test_adminapi_cluster_settings_marks_only_steamcmd_plugins_when_steamcmd_root_changes(tmp_path):
    orch = _StubOrchestrator(tmp_path)
    api = AdminAPI(orch)

    resp = api.set_cluster_config_fields({"steamcmd_root": r"D:\SteamCMD"})

    assert resp["status"] == "success"
    assert orch.mark_plugin_dirty_calls == ["ark"]
    assert orch.mark_instance_dirty_calls == [("ark", "10"), ("ark", "20")]
    assert orch.invalidate_runtime_calls == []


def test_adminapi_cluster_settings_rejects_unknown_fields(tmp_path):
    api = AdminAPI(_StubOrchestrator(tmp_path))

    resp = api.set_cluster_config_fields({"unknown": "x"})
    assert resp["status"] == "error"
    assert "Unknown cluster config fields" in resp["message"]

    resp2 = api.get_cluster_config_fields(["cluster_name", "unknown"])
    assert resp2["status"] == "error"
    assert "Unknown cluster config fields" in resp2["message"]


def test_adminapi_plugin_config_get_set_persists(tmp_path):
    orch = _StubOrchestrator(tmp_path)
    api = AdminAPI(orch)

    got = api.get_plugin_config_fields("ark")
    assert got["status"] == "success"
    assert got["data"]["fields"]["mods"] == []
    assert got["data"]["fields"]["passive_mods"] == []
    assert got["data"]["fields"]["test_mode"] is None

    set_resp = api.set_plugin_config_fields(
        "ark",
        {
            "mods": ["100"],
            "passive_mods": ["200"],
            "test_mode": False,
            "auto_update_on_restart": True,
            "scheduled_restart_enabled": True,
            "scheduled_restart_time": "05:00",
            "scheduled_update_check_enabled": True,
            "scheduled_update_check_time": "04:00",
            "scheduled_update_auto_apply": True,
            "default_game_port_start": 34000,
            "default_rcon_port_start": 35000,
        },
    )
    assert set_resp["status"] == "success"

    cfg_path = tmp_path / "plugins" / "ark" / "plugin_defaults.json"
    assert cfg_path.is_file()
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert raw["mods"] == ["100"]
    assert raw["passive_mods"] == ["200"]
    assert raw["test_mode"] is False
    assert raw["auto_update_on_restart"] is True
    assert raw["scheduled_restart_enabled"] is True
    assert raw["scheduled_restart_time"] == "05:00"
    assert raw["scheduled_update_check_enabled"] is True
    assert raw["scheduled_update_check_time"] == "04:00"
    assert raw["scheduled_update_auto_apply"] is True
    assert raw["default_game_port_start"] == 34000
    assert raw["default_rcon_port_start"] == 35000

    got2 = api.get_plugin_config_fields("ark")
    assert got2["status"] == "success"
    assert got2["data"]["fields"]["mods"] == ["100"]
    assert got2["data"]["fields"]["passive_mods"] == ["200"]
    assert got2["data"]["fields"]["test_mode"] is False
    assert got2["data"]["fields"]["auto_update_on_restart"] is True
    assert got2["data"]["fields"]["scheduled_restart_enabled"] is True
    assert got2["data"]["fields"]["scheduled_restart_time"] == "05:00"
    assert got2["data"]["fields"]["scheduled_update_check_enabled"] is True
    assert got2["data"]["fields"]["scheduled_update_check_time"] == "04:00"
    assert got2["data"]["fields"]["scheduled_update_auto_apply"] is True
    assert orch.mark_plugin_dirty_calls == ["ark"]
    assert orch.mark_instance_dirty_calls == [("ark", "10"), ("ark", "20")]
    assert orch.invalidate_runtime_calls == [("ark", None)]


def test_adminapi_plugin_config_managed_field_change_resyncs_managed_instance_fields(tmp_path):
    orch = _StubOrchestrator(tmp_path)
    api = AdminAPI(orch)

    resp = api.set_plugin_config_fields(
        "ark",
        {
            "rcon_enabled": True,
        },
    )

    assert resp["status"] == "success"
    expected_fields = ["admin_password", "pve", "rcon_enabled"]
    assert orch.clear_instance_config_calls == [
        ("ark", "10", expected_fields),
        ("ark", "20", expected_fields),
    ]
    assert orch.sync_instance_ini_calls == [
        ("ark", "10", expected_fields),
        ("ark", "20", expected_fields),
    ]


def test_adminapi_instance_config_marks_only_target_instance_dirty(tmp_path):
    orch = _StubOrchestrator(tmp_path)
    api = AdminAPI(orch)

    resp = api.set_instance_plugin_config_fields("ark", "10", {"map": "TheIsland_WP"})

    assert resp["status"] == "success"
    assert orch.mark_instance_dirty_calls == [("ark", "10")]
    assert orch.invalidate_runtime_calls == [("ark", "10")]


def test_adminapi_instance_config_returns_apply_result_from_sync(tmp_path):
    orch = _StubOrchestrator(tmp_path)
    api = AdminAPI(orch)

    resp = api.set_instance_plugin_config_fields("ark", "10", {"server_name": "Ark Cloud"})

    assert resp["status"] == "success"
    assert resp["data"]["apply_result"] == {"status": "success", "data": {"ok": True}}
    assert orch.sync_instance_ini_calls == [("ark", "10", ["server_name"])]


def test_adminapi_add_instance_marks_only_new_instance_dirty(tmp_path):
    orch = _StubOrchestrator(tmp_path)
    api = AdminAPI(orch)

    resp = api.add_instance("ark", "11")

    assert resp["status"] == "success"
    assert orch.mark_instance_dirty_calls == [("ark", "11")]
    assert orch.invalidate_runtime_calls == [("ark", "11")]


def test_adminapi_plugin_config_rejects_unknown_fields(tmp_path):
    api = AdminAPI(_StubOrchestrator(tmp_path))

    resp = api.set_plugin_config_fields("ark", {"unknown": "x"})
    assert resp["status"] == "error"
    assert "Unknown plugin config fields" in resp["message"]


def test_adminapi_get_plugin_capabilities_reads_registry_metadata(tmp_path):
    class _Registry:
        def get(self, name):
            if str(name) != "ark":
                return None
            return {
                "metadata": {
                    "name": "ark",
                    "capabilities": {
                        "install_server_app_id": "2430930",
                        "required_ports": [
                            {"name": "game", "proto": "udp"},
                            {"name": "rcon", "proto": "tcp"},
                        ],
                    },
                }
            }

    orch = _StubOrchestrator(tmp_path)
    orch._registry = _Registry()
    api = AdminAPI(orch)

    resp = api.get_plugin_capabilities("ark")
    assert resp["status"] == "success"
    assert resp["data"]["plugin_name"] == "ark"
    assert resp["data"]["capabilities"]["install_server_app_id"] == "2430930"
    assert resp["data"]["capabilities"]["required_ports"][0]["name"] == "game"


def test_adminapi_get_app_setup_report_routes_orchestrator_data(tmp_path):
    api = AdminAPI(_StubOrchestrator(tmp_path))

    resp = api.get_app_setup_report()

    assert resp["status"] == "success"
    assert resp["data"]["status"] == "missing"
    assert resp["data"]["results"][0]["id"] == "gameservers_root"


def test_app_setup_gate_clears_after_successful_steamcmd_install_with_relative_root(tmp_path, monkeypatch):
    import core.orchestrator as orchestrator_module
    import core.steamcmd as steamcmd_module

    class _Registry:
        def list_all(self):
            return ["ark"]

        def get_metadata(self, plugin_name):
            return {"dependencies": []}

        def get(self, plugin_name):
            return None

    cfg_root = tmp_path / "config"
    cfg_root.mkdir(parents=True, exist_ok=True)
    (cfg_root / "cluster_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "install_root_dir": str(tmp_path / "instances"),
                "backup_dir": str(tmp_path / "backups"),
                "cluster_name": "arkSA",
                "base_game_port": 30000,
                "base_rcon_port": 31000,
                "shared_mods": [],
                "shared_passive_mods": [],
                "instances": [],
                "gameservers_root": str(tmp_path / "GameServers"),
                "steamcmd_root": "relative-steamcmd",
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    effective_root = tmp_path / "relative-steamcmd"
    effective_exe = effective_root / "steamcmd.exe"

    orch = Orchestrator(_Registry(), StateManager(state_file=None), cluster_root=str(tmp_path))

    before = orch.get_app_setup_report()
    assert before["status"] == "install_available"
    assert [item for item in before["results"] if item["id"] == "steamcmd"][0]["details"] == str(effective_root)

    monkeypatch.setattr(orchestrator_module.os, "name", "nt")
    monkeypatch.setattr(
        steamcmd_module,
        "install_windows_bootstrap",
        lambda root: {
            "ok": True,
            "message": "SteamCMD installed successfully.",
            "steamcmd_root": str(effective_root),
            "steamcmd_exe": str(effective_exe),
        },
    )
    monkeypatch.setattr(
        steamcmd_module,
        "probe_steamcmd_executable",
        lambda path, **kwargs: (True, f"SteamCMD ready: {path}"),
    )

    effective_root.mkdir(parents=True, exist_ok=True)
    effective_exe.write_text("stub", encoding="utf-8")

    install_resp = orch.install_steamcmd()
    assert install_resp["status"] == "success"
    assert install_resp["data"]["steamcmd_root"] == str(effective_root)
    assert install_resp["data"]["steamcmd_exe"] == str(effective_exe)

    after = orch.get_app_setup_report()
    assert after["status"] == "installed"
    assert [item for item in after["results"] if item["id"] == "steamcmd"][0]["details"] == str(effective_exe)
