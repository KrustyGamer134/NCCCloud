import json
from datetime import datetime, timezone

from core.admin_api import AdminAPI
from core.orchestrator import Orchestrator
from core.state_manager import StateManager


class _FakeConnection:
    def __init__(self, handler):
        self._handler = handler
        self.requests = []

    def send_request(self, action, payload=None):
        call = (str(action), dict(payload or {}))
        self.requests.append(call)
        return self._handler(str(action), dict(payload or {}))


class _FakeRegistry:
    def __init__(self, connection):
        self._connection = connection

    def get(self, name):
        if str(name) != "ark":
            return None
        return {"connection": self._connection, "process": None}

    def list_all(self):
        return ["ark"]

    def load_all(self):
        return None


def _build_orchestrator(handler):
    connection = _FakeConnection(handler)
    registry = _FakeRegistry(connection)
    state = StateManager(state_file=None)
    orch = Orchestrator(registry, state, cluster_root=".")
    return orch, state, connection


def test_orchestrator_start_is_lifecycle_authority_and_calls_only_plugin_start_when_allowed(monkeypatch):
    actions = []

    def handler(action, payload):
        actions.append((action, dict(payload)))
        if action == "runtime_summary":
            return {"status": "success", "data": {"ok": True, "running": True, "ready": False, "version": {"installed": None, "running": None}}}
        if action == "start":
            return {"status": "success", "data": {"ok": True, "simulated": False}}
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, state, _conn = _build_orchestrator(handler)
    monkeypatch.setattr(orch, "get_instance_install_status", lambda plugin_name, instance_id: "INSTALLED")

    resp = orch.start_instance("ark", "10")

    assert resp["status"] == "success"
    assert actions == [("start", {"instance_id": "10"}), ("runtime_summary", {"instance_id": "10"})]
    assert state.get_state("ark", "10") == state.RUNNING
    assert orch.get_instance_last_action("ark", "10") == "start"


def test_orchestrator_start_stays_starting_until_runtime_truth_reports_running(monkeypatch):
    actions = []

    def handler(action, payload):
        actions.append((action, dict(payload)))
        if action == "runtime_summary":
            return {"status": "success", "data": {"ok": True, "running": False, "ready": False, "version": {"installed": None, "running": None}}}
        if action == "start":
            return {"status": "success", "data": {"ok": True, "simulated": False}}
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, state, _conn = _build_orchestrator(handler)
    monkeypatch.setattr(orch, "get_instance_install_status", lambda plugin_name, instance_id: "INSTALLED")

    resp = orch.start_instance("ark", "10")

    assert resp["status"] == "success"
    assert actions == [("start", {"instance_id": "10"}), ("runtime_summary", {"instance_id": "10"})]
    assert state.get_state("ark", "10") == state.STARTING
    assert orch.get_instance_last_action("ark", "10") == "start"


def test_orchestrator_start_syncs_ini_for_plugins_with_ini_settings(monkeypatch):
    actions = []

    def handler(action, payload):
        actions.append((action, dict(payload)))
        if action == "sync_ini_fields":
            return {"status": "success", "data": {"ok": True, "warnings": [], "errors": []}}
        if action == "runtime_summary":
            return {"status": "success", "data": {"ok": True, "running": True, "ready": False, "version": {"installed": None, "running": None}}}
        if action == "start":
            return {"status": "success", "data": {"ok": True, "simulated": False}}
        raise AssertionError(f"unexpected plugin action: {action}")

    class _MetadataRegistry(_FakeRegistry):
        def get_metadata(self, name):
            if str(name) != "ark":
                return {}
            return {"ini_settings": {"rcon_enabled": {"section": "ServerSettings", "key": "RCONEnabled"}}}

    connection = _FakeConnection(handler)
    registry = _MetadataRegistry(connection)
    state = StateManager(state_file=None)
    orch = Orchestrator(registry, state, cluster_root=".")
    monkeypatch.setattr(orch, "get_instance_install_status", lambda plugin_name, instance_id: "INSTALLED")

    resp = orch.start_instance("ark", "10")

    assert resp["status"] == "success"
    assert actions == [
        ("sync_ini_fields", {"instance_id": "10", "fields": ["mods", "passive_mods", "max_players", "game_port", "rcon_port", "rcon_enabled", "admin_password", "server_name", "display_name", "pve"]}),
        ("start", {"instance_id": "10"}),
        ("runtime_summary", {"instance_id": "10"}),
    ]


def test_orchestrator_start_reports_newer_runtime_version_after_start(monkeypatch):
    actions = []

    def handler(action, payload):
        actions.append((action, dict(payload)))
        if action == "start":
            return {"status": "success", "data": {"ok": True, "simulated": False, "details": "start complete"}}
        if action == "runtime_summary":
            return {
                "status": "success",
                "data": {
                    "ok": True,
                    "running": True,
                    "ready": True,
                    "version": {"installed": "84.19", "running": "84.26"},
                },
            }
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, state, _conn = _build_orchestrator(handler)
    monkeypatch.setattr(orch, "get_instance_install_status", lambda plugin_name, instance_id: "INSTALLED")
    orch._cached_runtime_summaries[("ark", "10")] = {
        "status": "success",
        "data": {"ok": True, "version": {"installed": "84.19", "running": "84.19"}},
    }

    resp = orch.start_instance("ark", "10")

    assert resp["status"] == "success"
    assert "Version notice: server reported newer version 84.26 (was 84.19)." in resp["data"]["details"]
    assert any(event.get("event_type") == "instance_version_advanced" for event in orch.get_events())


def test_check_update_enriches_response_with_build_compare():
    def handler(action, payload):
        if action == "check_update":
            assert payload["install_target"] == "master"
            return {"status": "success", "data": {"ok": True, "current_build_id": "22359937", "target_version": "22441125", "master_current_version": "84.28", "warnings": [], "errors": []}}
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, state, _conn = _build_orchestrator(handler)
    state.ensure_instance_exists("ark", "10")
    orch._cached_runtime_summaries[("ark", "10")] = {
        "status": "success",
        "data": {"ok": True, "version": {"installed": "84.19", "running": "84.19"}},
    }
    orch._current_build_for_update_compare = lambda plugin_name, instance_id: "22350000"

    resp = orch.check_update("ark", "10")

    assert resp["status"] == "success"
    assert resp["data"]["current_version"] == "84.19"
    assert resp["data"]["current_build_id"] == "22350000"
    assert resp["data"]["master_current_build_id"] == "22359937"
    assert resp["data"]["target_version"] == "22441125"
    assert resp["data"]["update_available"] is True
    assert resp["data"]["master_install_ready"] is False


def test_check_update_uses_build_ids_but_not_visible_server_versions(tmp_path):
    def handler(action, payload):
        if action == "check_update":
            assert payload["install_target"] == "master"
            return {"status": "success", "data": {"ok": True, "current_build_id": "22359937", "target_version": "22441125", "warnings": [], "errors": []}}
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, state, _conn = _build_orchestrator(handler)
    orch._cluster_root = str(tmp_path)
    instance10 = tmp_path / "plugins" / "ark" / "instances" / "10" / "config"
    instance10.mkdir(parents=True, exist_ok=True)
    (instance10 / "plugin_instance_config.json").write_text('{"schema_version":1,"map":"Ragnarok_WP"}', encoding="utf-8")
    instance11 = tmp_path / "plugins" / "ark" / "instances" / "11" / "config"
    instance11.mkdir(parents=True, exist_ok=True)
    (instance11 / "plugin_instance_config.json").write_text('{"schema_version":1,"map":"TheIsland_WP"}', encoding="utf-8")
    state.ensure_instance_exists("ark", "10")
    state.ensure_instance_exists("ark", "11")
    orch._cached_runtime_summaries[("ark", "10")] = {
        "status": "success",
        "data": {"ok": True, "version": {"installed": "84.19", "running": "84.19"}},
    }
    orch._cached_runtime_summaries[("ark", "11")] = {
        "status": "success",
        "data": {"ok": True, "version": {"installed": "84.28", "running": "84.28"}},
    }
    orch._current_build_for_update_compare = lambda plugin_name, instance_id: "22350000" if str(instance_id) == "10" else None

    resp = orch.check_update("ark", "10")

    assert resp["status"] == "success"
    assert resp["data"]["current_build_id"] == "22350000"
    assert resp["data"]["master_current_build_id"] == "22359937"
    assert resp["data"]["target_version"] == "22441125"
    assert resp["data"]["update_available"] is True


def test_prepare_master_install_routes_through_plugin_install_server():
    actions = []

    def handler(action, payload):
        actions.append((action, dict(payload)))
        if action == "install_server":
            return {
                "status": "success",
                "data": {
                    "ok": True,
                    "details": "install_server complete",
                    "install_root": r"E:\GameServers\.ncc\masters\ark\ArkSA",
                    "warnings": [],
                    "errors": [],
                },
            }
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, _state, _conn = _build_orchestrator(handler)
    orch._steamcmd_install_readiness_error = lambda plugin_name: None

    resp = orch.prepare_master_install("ark")

    assert resp["status"] == "success"
    assert resp["data"]["ok"] is True
    assert resp["data"]["install_target"] == "master"
    assert actions == [("install_server", {"install_target": "master"})]


def test_check_plugin_update_checks_master_once_and_enriches_all_instances(tmp_path):
    actions = []

    def handler(action, payload):
        actions.append((action, dict(payload)))
        if action == "check_update":
            return {"status": "success", "data": {"ok": True, "current_build_id": "22359937", "target_version": "22441125", "master_current_version": "84.28", "install_root": r"E:\GameServers\.ncc\masters\ark\ArkSA", "warnings": [], "errors": []}}
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, state, _conn = _build_orchestrator(handler)
    orch._cluster_root = str(tmp_path)
    orch._version_build_map = {}
    instance10 = tmp_path / "plugins" / "ark" / "instances" / "10" / "config"
    instance10.mkdir(parents=True, exist_ok=True)
    (instance10 / "plugin_instance_config.json").write_text('{"schema_version":1,"map":"TheIsland_WP"}', encoding="utf-8")
    instance11 = tmp_path / "plugins" / "ark" / "instances" / "11" / "config"
    instance11.mkdir(parents=True, exist_ok=True)
    (instance11 / "plugin_instance_config.json").write_text('{"schema_version":1,"map":"TheIsland_WP"}', encoding="utf-8")
    state.ensure_instance_exists("ark", "10")
    state.ensure_instance_exists("ark", "11")
    orch._cached_runtime_summaries[("ark", "10")] = {"status": "success", "data": {"ok": True, "version": {"installed": "84.19", "running": "84.19"}}}
    orch._cached_runtime_summaries[("ark", "11")] = {"status": "success", "data": {"ok": True, "version": {"installed": "84.28", "running": "84.28"}}}
    orch._current_build_for_update_compare = lambda plugin_name, instance_id: "22350000" if str(instance_id) == "10" else "22441125"

    resp = orch.check_plugin_update("ark")

    assert resp["status"] == "success"
    assert resp["data"]["master_install_ready"] is True
    assert resp["data"]["master_current_build_id"] == "22359937"
    assert resp["data"]["instances"]["10"]["master_current_build_id"] == "22359937"
    assert resp["data"]["instances"]["10"]["update_available"] is True
    assert resp["data"]["instances"]["11"]["update_available"] is False
    assert actions == [("check_update", {"install_target": "master"})]


def test_check_plugin_update_uses_seeded_build_version_mapping_file(tmp_path):
    def handler(action, payload):
        if action == "check_update":
            return {
                "status": "success",
                "data": {
                    "ok": True,
                    "current_build_id": None,
                    "target_version": "22441125",
                    "master_current_version": None,
                    "install_root": r"E:\GameServers\.ncc\masters\ark\ArkSA",
                    "warnings": [],
                    "errors": [],
                },
            }
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, state, _conn = _build_orchestrator(handler)
    orch._cluster_root = str(tmp_path)
    map_root = tmp_path / ".ncc"
    map_root.mkdir(parents=True, exist_ok=True)
    (map_root / "version_build_map.json").write_text(
        json.dumps({"plugins": {"ark": {"builds": {"22441125": "84.28"}}}}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    orch._version_build_map = orch._load_version_build_map()
    instance10 = tmp_path / "plugins" / "ark" / "instances" / "10" / "config"
    instance10.mkdir(parents=True, exist_ok=True)
    (instance10 / "plugin_instance_config.json").write_text('{"schema_version":1,"map":"Ragnarok_WP"}', encoding="utf-8")
    instance11 = tmp_path / "plugins" / "ark" / "instances" / "11" / "config"
    instance11.mkdir(parents=True, exist_ok=True)
    (instance11 / "plugin_instance_config.json").write_text('{"schema_version":1,"map":"TheIsland_WP"}', encoding="utf-8")
    state.ensure_instance_exists("ark", "10")
    state.ensure_instance_exists("ark", "11")
    orch._cached_runtime_summaries[("ark", "10")] = {
        "status": "success",
        "data": {"ok": True, "version": {"installed": "84.19", "running": "84.19"}},
    }
    orch._cached_runtime_summaries[("ark", "11")] = {
        "status": "success",
        "data": {"ok": True, "version": {"installed": "84.28", "running": "84.28"}},
    }
    orch._current_build_for_update_compare = lambda plugin_name, instance_id: None

    resp = orch.check_plugin_update("ark")

    assert resp["data"]["master_current_version"] == "84.28"
    assert resp["data"]["instances"]["10"]["update_available"] is True
    assert resp["data"]["instances"]["11"]["update_available"] is False
    assert orch._mapped_version_for_build("ark", "22441125") == "84.28"


def test_check_plugin_update_uses_stored_master_build_from_mapping_file(tmp_path):
    def handler(action, payload):
        if action == "check_update":
            return {
                "status": "success",
                "data": {
                    "ok": True,
                    "current_build_id": None,
                    "target_version": "22450000",
                    "master_current_version": None,
                    "install_root": r"E:\GameServers\.ncc\masters\ark\ArkSA",
                    "warnings": [],
                    "errors": [],
                },
            }
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, state, _conn = _build_orchestrator(handler)
    orch._cluster_root = str(tmp_path)
    map_root = tmp_path / ".ncc"
    map_root.mkdir(parents=True, exist_ok=True)
    (map_root / "version_build_map.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "ark": {
                        "master_current_build_id": "22441125",
                        "builds": {"22441125": "84.28"},
                    }
                }
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    orch._load_version_build_map()
    instance10 = tmp_path / "plugins" / "ark" / "instances" / "10" / "config"
    instance10.mkdir(parents=True, exist_ok=True)
    (instance10 / "plugin_instance_config.json").write_text('{"schema_version":1,"map":"Ragnarok_WP"}', encoding="utf-8")
    state.ensure_instance_exists("ark", "10")
    orch._cached_runtime_summaries[("ark", "10")] = {
        "status": "success",
        "data": {"ok": True, "version": {"installed": "84.19", "running": "84.19"}},
    }
    orch._current_build_for_update_compare = lambda plugin_name, instance_id: None

    resp = orch.check_plugin_update("ark")

    assert resp["data"]["master_current_build_id"] == "22441125"
    assert resp["data"]["master_current_version"] == "84.28"


def test_check_plugin_update_reloads_build_version_mapping_after_startup(tmp_path):
    def handler(action, payload):
        if action == "check_update":
            return {
                "status": "success",
                "data": {
                    "ok": True,
                    "current_build_id": "22441125",
                    "target_version": "22441125",
                    "master_current_version": None,
                    "install_root": r"E:\GameServers\.ncc\masters\ark\ArkSA",
                    "warnings": [],
                    "errors": [],
                },
            }
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, state, _conn = _build_orchestrator(handler)
    orch._cluster_root = str(tmp_path)
    orch._version_build_map = {}
    orch._version_build_state = {}
    map_root = tmp_path / ".ncc"
    map_root.mkdir(parents=True, exist_ok=True)
    (map_root / "version_build_map.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "ark": {
                        "master_current_build_id": "22441125",
                        "builds": {"22441125": "84.28"},
                    }
                }
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    instance10 = tmp_path / "plugins" / "ark" / "instances" / "10" / "config"
    instance10.mkdir(parents=True, exist_ok=True)
    (instance10 / "plugin_instance_config.json").write_text('{"schema_version":1,"map":"Ragnarok_WP"}', encoding="utf-8")
    state.ensure_instance_exists("ark", "10")
    orch._cached_runtime_summaries[("ark", "10")] = {
        "status": "success",
        "data": {"ok": True, "version": {"installed": "84.19", "running": "84.19"}},
    }
    orch._current_build_for_update_compare = lambda plugin_name, instance_id: None

    resp = orch.check_plugin_update("ark")

    assert resp["data"]["master_current_build_id"] == "22441125"
    assert resp["data"]["master_current_version"] == "84.28"


def test_check_plugin_update_prefers_gameservers_root_version_build_map(tmp_path):
    def handler(action, payload):
        if action == "check_update":
            return {
                "status": "success",
                "data": {
                    "ok": True,
                    "current_build_id": "22441125",
                    "target_version": "22441125",
                    "master_current_version": None,
                    "install_root": r"E:\GameServers\.ncc\masters\ark\ArkSA",
                    "warnings": [],
                    "errors": [],
                },
            }
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, state, _conn = _build_orchestrator(handler)
    orch._cluster_root = str(tmp_path)
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "cluster_config.json").write_text(
        json.dumps(
            {
                "install_root_dir": str(tmp_path / "instances"),
                "backup_dir": str(tmp_path / "backups"),
                "base_game_port": 7777,
                "base_rcon_port": 27020,
                "gameservers_root": str(tmp_path / "GameServers"),
                "steamcmd_root": str(tmp_path / "steamcmd"),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    map_root = tmp_path / "GameServers" / ".ncc"
    map_root.mkdir(parents=True, exist_ok=True)
    (map_root / "version_build_map.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "ark": {
                        "master_current_build_id": "22441125",
                        "builds": {"22441125": "84.28"},
                    }
                }
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    instance10 = tmp_path / "plugins" / "ark" / "instances" / "10" / "config"
    instance10.mkdir(parents=True, exist_ok=True)
    (instance10 / "plugin_instance_config.json").write_text('{"schema_version":1,"map":"Ragnarok_WP"}', encoding="utf-8")
    state.ensure_instance_exists("ark", "10")
    orch._cached_runtime_summaries[("ark", "10")] = {
        "status": "success",
        "data": {"ok": True, "version": {"installed": "84.19", "running": "84.19"}},
    }
    orch._current_build_for_update_compare = lambda plugin_name, instance_id: None

    resp = orch.check_plugin_update("ark")

    assert resp["data"]["master_current_build_id"] == "22441125"
    assert resp["data"]["master_current_version"] == "84.28"


def test_check_plugin_update_maps_master_version_from_returned_master_build_id(tmp_path):
    def handler(action, payload):
        if action == "check_update":
            return {
                "status": "success",
                "data": {
                    "ok": True,
                    "current_build_id": "22441125",
                    "target_version": "22441125",
                    "master_current_version": None,
                    "install_root": r"E:\GameServers\.ncc\masters\ark\ArkSA",
                    "warnings": [],
                    "errors": [],
                },
            }
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, state, _conn = _build_orchestrator(handler)
    orch._cluster_root = str(tmp_path)
    map_root = tmp_path / ".ncc"
    map_root.mkdir(parents=True, exist_ok=True)
    (map_root / "version_build_map.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "ark": {
                        "master_current_build_id": "22441125",
                        "builds": {"22441125": "84.28"},
                    }
                }
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    instance10 = tmp_path / "plugins" / "ark" / "instances" / "10" / "config"
    instance10.mkdir(parents=True, exist_ok=True)
    (instance10 / "plugin_instance_config.json").write_text('{"schema_version":1,"map":"Ragnarok_WP"}', encoding="utf-8")
    state.ensure_instance_exists("ark", "10")
    orch._cached_runtime_summaries[("ark", "10")] = {
        "status": "success",
        "data": {"ok": True, "version": {"installed": "84.19", "running": "84.19"}},
    }
    orch._current_build_for_update_compare = lambda plugin_name, instance_id: None

    resp = orch.check_plugin_update("ark")

    assert resp["data"]["master_current_build_id"] == "22441125"
    assert resp["data"]["master_current_version"] == "84.28"


def test_check_plugin_update_refreshes_runtime_summary_when_cached_version_missing(tmp_path):
    actions = []

    def handler(action, payload):
        actions.append((action, dict(payload)))
        if action == "check_update":
            return {
                "status": "success",
                "data": {
                    "ok": True,
                    "current_build_id": "22359937",
                    "target_version": "22441125",
                    "master_current_version": "84.28",
                    "install_root": r"E:\GameServers\.ncc\masters\ark\ArkSA",
                    "warnings": [],
                    "errors": [],
                },
            }
        if action == "runtime_summary":
            return {
                "status": "success",
                "data": {
                    "ok": True,
                    "version": {"installed": "84.19", "running": None},
                    "running": False,
                    "ready": False,
                },
            }
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, state, _conn = _build_orchestrator(handler)
    orch._cluster_root = str(tmp_path)
    instance10 = tmp_path / "plugins" / "ark" / "instances" / "10" / "config"
    instance10.mkdir(parents=True, exist_ok=True)
    (instance10 / "plugin_instance_config.json").write_text('{"schema_version":1,"map":"Ragnarok_WP"}', encoding="utf-8")
    state.ensure_instance_exists("ark", "10")
    orch._cached_runtime_summaries[("ark", "10")] = {
        "status": "success",
        "data": {"ok": True, "version": {"installed": None, "running": None}},
    }
    orch._runtime_summary_last_updated[("ark", "10")] = 0.0
    orch._current_build_for_update_compare = lambda plugin_name, instance_id: "22350000"

    resp = orch.check_plugin_update("ark")

    assert resp["status"] == "success"
    assert resp["data"]["instances"]["10"]["current_version"] == "84.19"
    assert resp["data"]["instances"]["10"]["update_available"] is True
    assert actions == [
        ("check_update", {"install_target": "master"}),
        ("runtime_summary", {"instance_id": "10"}),
    ]


def test_check_plugin_update_bypasses_freshness_guard_when_cached_version_missing(tmp_path, monkeypatch):
    actions = []

    def handler(action, payload):
        actions.append((action, dict(payload)))
        if action == "check_update":
            return {
                "status": "success",
                "data": {
                    "ok": True,
                    "current_build_id": "22359937",
                    "target_version": "22441125",
                    "master_current_version": "84.28",
                    "install_root": r"E:\GameServers\.ncc\masters\ark\ArkSA",
                    "warnings": [],
                    "errors": [],
                },
            }
        if action == "runtime_summary":
            return {
                "status": "success",
                "data": {
                    "ok": True,
                    "version": {"installed": "84.19", "running": None},
                    "running": False,
                    "ready": False,
                },
            }
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, state, _conn = _build_orchestrator(handler)
    orch._cluster_root = str(tmp_path)
    monkeypatch.setattr(orch, "_now", lambda: 100.0)
    instance10 = tmp_path / "plugins" / "ark" / "instances" / "10" / "config"
    instance10.mkdir(parents=True, exist_ok=True)
    (instance10 / "plugin_instance_config.json").write_text('{"schema_version":1,"map":"Ragnarok_WP"}', encoding="utf-8")
    state.ensure_instance_exists("ark", "10")
    orch._cached_runtime_summaries[("ark", "10")] = {
        "status": "success",
        "data": {"ok": True, "version": {"installed": None, "running": None}},
    }
    orch._runtime_summary_last_updated[("ark", "10")] = 100.0
    orch._current_build_for_update_compare = lambda plugin_name, instance_id: "22350000"

    resp = orch.check_plugin_update("ark")

    assert resp["status"] == "success"
    assert resp["data"]["instances"]["10"]["current_version"] == "84.19"
    assert resp["data"]["instances"]["10"]["update_available"] is True
    assert actions == [
        ("check_update", {"install_target": "master"}),
        ("runtime_summary", {"instance_id": "10"}),
    ]


def test_orchestrator_start_blocks_before_plugin_call_when_install_gate_fails(monkeypatch):
    def handler(action, payload):
        raise AssertionError("plugin start should not be called when install gate fails")

    orch, state, _conn = _build_orchestrator(handler)
    monkeypatch.setattr(orch, "get_instance_install_status", lambda plugin_name, instance_id: "NOT_INSTALLED")

    resp = orch.start_instance("ark", "10")

    assert resp == {"status": "error", "message": "Instance not installed. Run: install <plugin> <instance>"}
    assert state.get_state("ark", "10") == state.STOPPED


def test_orchestrator_stop_gates_on_runtime_truth_then_uses_graceful_stop_and_reconcile():
    actions = []
    runtime_values = iter([True, False])

    def handler(action, payload):
        actions.append((action, dict(payload)))
        if action == "runtime_summary":
            return {"status": "success", "data": {"ok": True, "running": next(runtime_values), "ready": False}}
        if action == "graceful_stop":
            return {"status": "success", "data": {"ok": True, "simulated": False}}
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, state, _conn = _build_orchestrator(handler)
    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.RUNNING)

    resp = orch.stop_instance("ark", "10")

    assert resp["status"] == "success"
    assert actions == [
        ("runtime_summary", {"instance_id": "10"}),
        ("graceful_stop", {"instance_id": "10"}),
        ("runtime_summary", {"instance_id": "10"}),
    ]
    assert state.get_state("ark", "10") == state.STOPPED
    assert orch.get_instance_last_action("ark", "10") == "stop"


def test_orchestrator_manual_restart_owns_runtime_gate_and_plugin_call_sequence():
    actions = []
    runtime_values = iter([True, False, True])

    def handler(action, payload):
        actions.append((action, dict(payload)))
        if action == "runtime_summary":
            return {"status": "success", "data": {"ok": True, "running": next(runtime_values), "ready": True}}
        if action == "graceful_stop":
            return {"status": "success", "data": {"ok": True, "stopped": True, "simulated": False}}
        if action == "start":
            return {"status": "success", "data": {"ok": True, "simulated": False}}
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, state, _conn = _build_orchestrator(handler)
    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.RUNNING)

    resp = orch.restart_instance("ark", "10", restart_reason="manual")

    assert resp["status"] == "success"
    assert actions == [
        ("runtime_summary", {"instance_id": "10"}),
        ("graceful_stop", {"instance_id": "10"}),
        ("runtime_summary", {"instance_id": "10"}),
        ("start", {"instance_id": "10"}),
        ("runtime_summary", {"instance_id": "10"}),
    ]
    assert state.get_state("ark", "10") == state.RUNNING
    assert orch.get_instance_last_action("ark", "10") == "restart"


def test_orchestrator_manual_restart_stays_restarting_when_post_start_runtime_disagrees():
    actions = []
    runtime_values = iter([True, False, False])

    def handler(action, payload):
        actions.append((action, dict(payload)))
        if action == "runtime_summary":
            return {"status": "success", "data": {"ok": True, "running": next(runtime_values), "ready": False}}
        if action == "graceful_stop":
            return {"status": "success", "data": {"ok": True, "stopped": True, "simulated": False}}
        if action == "start":
            return {"status": "success", "data": {"ok": True, "simulated": False}}
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, state, _conn = _build_orchestrator(handler)
    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.RUNNING)

    resp = orch.restart_instance("ark", "10", restart_reason="manual")

    assert resp["status"] == "success"
    assert actions == [
        ("runtime_summary", {"instance_id": "10"}),
        ("graceful_stop", {"instance_id": "10"}),
        ("runtime_summary", {"instance_id": "10"}),
        ("start", {"instance_id": "10"}),
        ("runtime_summary", {"instance_id": "10"}),
    ]
    assert state.get_state("ark", "10") == state.RESTARTING
    assert orch.get_instance_last_action("ark", "10") == "restart"


def test_orchestrator_scheduled_restart_skips_runtime_gate_and_resets_stability_only():
    actions = []

    def handler(action, payload):
        actions.append((action, dict(payload)))
        if action == "graceful_stop":
            return {"status": "success", "data": {"ok": True, "stopped": True, "simulated": False}}
        if action == "start":
            return {"status": "success", "data": {"ok": True, "simulated": False}}
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, state, _conn = _build_orchestrator(handler)
    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.STOPPED)
    key = orch._ensure_counter_entry("ark", "10")
    orch._crash_counters[key]["crash_total_count"] = 4
    orch._crash_counters[key]["crash_stability_count"] = 9

    resp = orch.restart_instance("ark", "10", restart_reason="scheduled")

    assert resp["status"] == "success"
    assert actions == [
        ("graceful_stop", {"instance_id": "10"}),
        ("start", {"instance_id": "10"}),
    ]
    assert orch.get_crash_total_count("ark", "10") == 4
    assert orch.get_crash_stability_count("ark", "10") == 0
    assert state.get_state("ark", "10") == state.RUNNING


def test_orchestrator_tick_scheduled_update_check_auto_applies(tmp_path, monkeypatch):
    orch, state, _conn = _build_orchestrator(lambda action, payload: {"status": "success", "data": {"ok": True}})
    orch._cluster_root = str(tmp_path)
    plugin_dir = tmp_path / "plugins" / "ark"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scheduled_update_check_enabled": True,
                "scheduled_update_check_time": "04:00",
                "scheduled_update_auto_apply": True,
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    for instance_id in ("10", "11"):
        instance_root = tmp_path / "plugins" / "ark" / "instances" / instance_id
        instance_root.mkdir(parents=True, exist_ok=True)
        (instance_root / "instance.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        orch,
        "check_plugin_update",
        lambda plugin_name: {
            "status": "success",
            "data": {"instances": {"10": {"update_available": True}, "11": {"update_available": True}}},
        },
    )
    monkeypatch.setattr(orch, "prepare_master_install", lambda plugin_name: {"status": "success", "data": {"ok": True}})
    monkeypatch.setattr(orch, "get_instance_install_status", lambda plugin_name, instance_id: "INSTALLED")
    monkeypatch.setattr(orch, "_runtime_running", lambda plugin_name, instance_id: str(instance_id) == "10")
    update_calls = []
    install_calls = []
    monkeypatch.setattr(orch, "update_instance", lambda plugin_name, instance_id: update_calls.append((plugin_name, instance_id)) or {"status": "success"})
    monkeypatch.setattr(orch, "install_server_instance", lambda plugin_name, instance_id: install_calls.append((plugin_name, instance_id)) or {"status": "success"})

    out = orch.tick_scheduled_tasks(current_datetime=datetime(2026, 3, 23, 4, 0, tzinfo=timezone.utc))

    assert update_calls == [("ark", "10")]
    assert install_calls == [("ark", "11")]
    assert out["update_checks"][0]["plugin_name"] == "ark"
    assert orch._scheduled_policy_state["ark"]["last_update_check_date"] == "2026-03-23"
    assert orch._scheduled_policy_state["ark"]["last_scheduled_apply_result"] == "Applied: 2/2 instance updates"


def test_orchestrator_tick_scheduled_restart_restarts_running_instances_once_per_day(tmp_path, monkeypatch):
    orch, state, _conn = _build_orchestrator(lambda action, payload: {"status": "success", "data": {"ok": True}})
    orch._cluster_root = str(tmp_path)
    plugin_dir = tmp_path / "plugins" / "ark"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scheduled_restart_enabled": True,
                "scheduled_restart_time": "05:00",
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    for instance_id in ("10", "11"):
        instance_root = tmp_path / "plugins" / "ark" / "instances" / instance_id
        instance_root.mkdir(parents=True, exist_ok=True)
        (instance_root / "instance.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(orch, "_runtime_running", lambda plugin_name, instance_id: str(instance_id) == "10")
    restart_calls = []
    monkeypatch.setattr(
        orch,
        "restart_instance",
        lambda plugin_name, instance_id, restart_reason="crash": restart_calls.append((plugin_name, instance_id, restart_reason)) or {"status": "success"},
    )

    first = orch.tick_scheduled_tasks(current_datetime=datetime(2026, 3, 23, 5, 0, tzinfo=timezone.utc))
    second = orch.tick_scheduled_tasks(current_datetime=datetime(2026, 3, 23, 6, 0, tzinfo=timezone.utc))

    assert restart_calls == [("ark", "10", "scheduled")]
    assert first["scheduled_restarts"][0]["plugin_name"] == "ark"
    assert second["scheduled_restarts"] == []


def test_orchestrator_tick_scheduled_update_check_notifies_when_apply_blocked(tmp_path, monkeypatch):
    orch, _state, _conn = _build_orchestrator(lambda action, payload: {"status": "success", "data": {"ok": True}})
    orch._cluster_root = str(tmp_path)
    plugin_dir = tmp_path / "plugins" / "ark"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scheduled_update_check_enabled": True,
                "scheduled_update_check_time": "04:00",
                "scheduled_update_auto_apply": True,
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        orch,
        "check_plugin_update",
        lambda plugin_name: {
            "status": "success",
            "data": {
                "master_install_ready": False,
                "instances": {"10": {"update_available": True}},
            },
        },
    )
    monkeypatch.setattr(orch, "prepare_master_install", lambda plugin_name: {"status": "error", "message": "SteamCMD not ready"})

    out = orch.tick_scheduled_tasks(current_datetime=datetime(2026, 3, 23, 4, 0, tzinfo=timezone.utc))

    assert out["update_checks"][0]["outcome"] == "failed"
    assert out["notifications"][0]["title"] == "Scheduled Update Apply Blocked"
    assert "SteamCMD not ready" in out["notifications"][0]["message"]
    assert orch._scheduled_policy_state["ark"]["last_scheduled_apply_result"] == "Failed: updates available, apply blocked (SteamCMD not ready)"


def test_orchestrator_tick_scheduled_restart_skips_transitional_instances(tmp_path, monkeypatch):
    orch, state, _conn = _build_orchestrator(lambda action, payload: {"status": "success", "data": {"ok": True}})
    orch._cluster_root = str(tmp_path)
    plugin_dir = tmp_path / "plugins" / "ark"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scheduled_restart_enabled": True,
                "scheduled_restart_time": "05:00",
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    for instance_id in ("10", "11"):
        instance_root = tmp_path / "plugins" / "ark" / "instances" / instance_id
        instance_root.mkdir(parents=True, exist_ok=True)
        (instance_root / "instance.json").write_text("{}", encoding="utf-8")
    state.ensure_instance_exists("ark", "10")
    state.ensure_instance_exists("ark", "11")
    state.set_state("ark", "10", state.RUNNING)
    state.set_state("ark", "11", state.RESTARTING)
    monkeypatch.setattr(orch, "_runtime_running", lambda plugin_name, instance_id: True)
    restart_calls = []
    monkeypatch.setattr(
        orch,
        "restart_instance",
        lambda plugin_name, instance_id, restart_reason="crash": restart_calls.append((plugin_name, instance_id, restart_reason)) or {"status": "success"},
    )

    out = orch.tick_scheduled_tasks(current_datetime=datetime(2026, 3, 23, 5, 0, tzinfo=timezone.utc))

    assert restart_calls == [("ark", "10", "scheduled")]
    assert out["scheduled_restarts"][0]["outcome"] == "applied"
    assert out["scheduled_restarts"][0]["skipped_instances"] == [{"instance_id": "11", "reason": "instance already restarting or transitioning"}]


def test_orchestrator_get_plugin_schedule_status_reports_next_and_last_values(tmp_path, monkeypatch):
    orch, _state, _conn = _build_orchestrator(lambda action, payload: {"status": "success", "data": {"ok": True}})
    orch._cluster_root = str(tmp_path)
    plugin_dir = tmp_path / "plugins" / "ark"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scheduled_update_check_enabled": True,
                "scheduled_update_check_time": "04:00",
                "scheduled_update_auto_apply": True,
                "scheduled_restart_enabled": True,
                "scheduled_restart_time": "05:30",
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    orch._scheduled_policy_state["ark"] = {
        "last_update_check_date": "2026-03-23",
        "last_update_check_at": "2026-03-23T04:00:00+00:00",
        "last_update_check_result": "Updates available",
        "last_scheduled_apply_at": "2026-03-23T04:01:00+00:00",
        "last_scheduled_apply_result": "Applied 2/2 instance updates",
        "last_restart_date": "2026-03-22",
        "last_restart_at": "2026-03-22T05:30:00+00:00",
        "last_restart_result": "Restarted 1/1 running instances",
    }

    out = orch.get_plugin_schedule_status("ark", current_datetime=datetime(2026, 3, 23, 4, 30, tzinfo=timezone.utc))

    assert out["plugin_name"] == "ark"
    assert out["scheduled_update_check_enabled"] is True
    assert out["scheduled_update_auto_apply"] is True
    assert out["next_scheduled_update_check_at"] == "2026-03-24T04:00:00+00:00"
    assert out["last_update_check_at"] == "2026-03-23T04:00:00+00:00"
    assert out["last_scheduled_apply_result"] == "Applied 2/2 instance updates"
    assert out["scheduled_restart_enabled"] is True
    assert out["next_scheduled_restart_at"] == "2026-03-23T05:30:00+00:00"
    assert out["last_scheduled_restart_at"] == "2026-03-22T05:30:00+00:00"


def test_orchestrator_disable_and_reenable_are_core_owned_without_plugin_calls():
    def handler(action, payload):
        raise AssertionError("disable/reenable must not call plugin actions")

    orch, state, _conn = _build_orchestrator(handler)
    key = orch._ensure_counter_entry("ark", "10")
    orch._crash_counters[key]["crash_total_count"] = 3
    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.RUNNING)

    disable = orch.disable_instance("ark", "10", reason="manual")
    reenable = orch.reenable_instance("ark", "10", reason="manual")

    assert disable == {"status": "success", "message": "Disabled: manual"}
    assert reenable == {"status": "success", "message": "Re-enabled: manual"}
    assert orch.get_crash_total_count("ark", "10") == 0
    assert state.get_state("ark", "10") == state.STOPPED


def test_adminapi_lifecycle_methods_continue_to_delegate_to_orchestrator_authority():
    class _LifecycleOnlyOrchestrator:
        def __init__(self):
            self.calls = []

        def start_instance(self, plugin_name, instance_id):
            self.calls.append(("start_instance", str(plugin_name), str(instance_id)))
            return {"status": "success"}

        def stop_instance(self, plugin_name, instance_id):
            self.calls.append(("stop_instance", str(plugin_name), str(instance_id)))
            return {"status": "success"}

        def restart_instance(self, plugin_name, instance_id, restart_reason="manual"):
            self.calls.append(("restart_instance", str(plugin_name), str(instance_id), str(restart_reason)))
            return {"status": "success"}

        def disable_instance(self, plugin_name, instance_id, reason="manual"):
            self.calls.append(("disable_instance", str(plugin_name), str(instance_id), str(reason)))
            return {"status": "success"}

        def reenable_instance(self, plugin_name, instance_id, reason="manual"):
            self.calls.append(("reenable_instance", str(plugin_name), str(instance_id), str(reason)))
            return {"status": "success"}

        def send_action(self, plugin_name, action, payload=None):
            raise AssertionError("AdminAPI lifecycle methods must not bypass Orchestrator to call send_action directly")

    orch = _LifecycleOnlyOrchestrator()
    api = AdminAPI(orch)

    assert api.start_instance("ark", "10")["status"] == "success"
    assert api.stop_instance("ark", "10")["status"] == "success"
    assert api.restart_instance("ark", "10", restart_reason="manual")["status"] == "success"
    assert api.disable_instance("ark", "10", reason="manual")["status"] == "success"
    assert api.enable_instance("ark", "10", reason="manual")["status"] == "success"

    assert orch.calls == [
        ("start_instance", "ark", "10"),
        ("stop_instance", "ark", "10"),
        ("restart_instance", "ark", "10", "manual"),
        ("disable_instance", "ark", "10", "manual"),
        ("reenable_instance", "ark", "10", "manual"),
    ]


def test_refresh_runtime_summary_reuses_fresh_cached_result():
    actions = []

    def handler(action, payload):
        actions.append((action, dict(payload)))
        if action == "runtime_summary":
            return {"status": "success", "data": {"ok": True, "running": True, "ready": False}}
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, _state, _conn = _build_orchestrator(handler)
    times = iter([10.0, 10.1, 10.2])
    orch._now = lambda: next(times)

    first = orch.refresh_runtime_summary("ark", "10")
    second = orch.refresh_runtime_summary("ark", "10")

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert actions == [("runtime_summary", {"instance_id": "10"})]


def test_inspect_runtime_status_reuses_fresh_cached_result():
    actions = []

    def handler(action, payload):
        actions.append((action, dict(payload)))
        if action == "runtime_status":
            return {"status": "success", "data": {"ok": True, "running": True, "ready": True}}
        raise AssertionError(f"unexpected plugin action: {action}")

    orch, _state, _conn = _build_orchestrator(handler)
    times = iter([20.0, 20.25, 20.5])
    orch._now = lambda: next(times)

    first = orch.inspect_runtime_status("ark", "10")
    second = orch.inspect_runtime_status("ark", "10")

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert actions == [("runtime_status", {"instance_id": "10"})]
