import json
from pathlib import Path

from core.admin_api import AdminAPI
from core.plugin_handler import PluginHandler
from core.plugin_registry import PluginRegistry


class _AdminOrchestratorStub:
    def __init__(self):
        self.calls = []

    def send_action(self, plugin_name, action, payload=None):
        call = ("send_action", str(plugin_name), str(action), dict(payload or {}))
        self.calls.append(call)
        return {"status": "success", "data": {"plugin": str(plugin_name), "action": str(action), "payload": dict(payload or {})}}

    def start_instance(self, plugin_name, instance_id):
        self.calls.append(("start_instance", str(plugin_name), str(instance_id)))
        return {"status": "success", "data": {"action": "start"}}

    def stop_instance(self, plugin_name, instance_id):
        self.calls.append(("stop_instance", str(plugin_name), str(instance_id)))
        return {"status": "success", "data": {"action": "stop"}}

    def restart_instance(self, plugin_name, instance_id, restart_reason="manual"):
        self.calls.append(("restart_instance", str(plugin_name), str(instance_id), str(restart_reason)))
        return {"status": "success", "data": {"action": "restart", "reason": str(restart_reason)}}

    def disable_instance(self, plugin_name, instance_id, reason="manual"):
        self.calls.append(("disable_instance", str(plugin_name), str(instance_id), str(reason)))
        return {"status": "success", "message": "disabled"}

    def reenable_instance(self, plugin_name, instance_id, reason="manual"):
        self.calls.append(("reenable_instance", str(plugin_name), str(instance_id), str(reason)))
        return {"status": "success", "message": "enabled"}


class _FallbackInstallServerOrchestrator(_AdminOrchestratorStub):
    pass


class _PreferredInstallServerOrchestrator(_AdminOrchestratorStub):
    def install_server_instance(self, plugin_name, instance_id):
        self.calls.append(("install_server_instance", str(plugin_name), str(instance_id)))
        return {"status": "success", "data": {"action": "install_server_instance"}}


class _PreferredCheckUpdateOrchestrator(_AdminOrchestratorStub):
    def check_update(self, plugin_name, instance_id):
        self.calls.append(("check_update", str(plugin_name), str(instance_id)))
        return {"status": "success", "data": {"action": "check_update"}}


class _PreferredDiscoverServersOrchestrator(_AdminOrchestratorStub):
    def discover_servers(self, plugin_name):
        self.calls.append(("discover_servers", str(plugin_name)))
        return {"status": "success", "data": {"action": "discover_servers"}}


class _PreferredImportServerOrchestrator(_AdminOrchestratorStub):
    def import_server(self, plugin_name, candidate):
        self.calls.append(("import_server", str(plugin_name), dict(candidate or {})))
        return {"status": "success", "data": {"action": "import_server"}}


class _PreferredAllocatePortsOrchestrator(_AdminOrchestratorStub):
    def allocate_instance_ports(self, plugin_name):
        self.calls.append(("allocate_instance_ports", str(plugin_name)))
        return {"status": "success", "data": {"game_port": 32000, "rcon_port": 33000}}


class _PreferredNextInstanceIdOrchestrator(_AdminOrchestratorStub):
    def suggest_next_instance_id(self, plugin_name):
        self.calls.append(("suggest_next_instance_id", str(plugin_name)))
        return {"status": "success", "data": {"instance_id": "12"}}


class _PreferredUpdateInstanceOrchestrator(_AdminOrchestratorStub):
    def update_instance(self, plugin_name, instance_id):
        self.calls.append(("update_instance", str(plugin_name), str(instance_id)))
        return {"status": "success", "data": {"action": "update_instance"}}


class _PreferredInstallSteamcmdOrchestrator(_AdminOrchestratorStub):
    def install_steamcmd(self):
        self.calls.append(("install_steamcmd",))
        return {"status": "success", "data": {"ok": True, "details": "SteamCMD installed successfully."}}


def _make_handler(tmp_path):
    real_ark = Path(__file__).resolve().parents[1] / "plugins" / "ark"
    with open(real_ark / "plugin.json", encoding="utf-8") as f:
        plugin_json = json.load(f)
    plugin_dir = tmp_path / "plugins" / "ark"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    return PluginHandler(
        plugin_json=plugin_json,
        plugin_dir=str(plugin_dir),
        cluster_root=str(tmp_path),
    )


def test_adminapi_direct_plugin_action_wrappers_route_to_send_action():
    orch = _AdminOrchestratorStub()
    api = AdminAPI(orch)

    assert api.validate_plugin("ark", instance_id="10", strict=True)["status"] == "success"
    assert api.install_deps("ark", "10")["status"] == "success"
    assert api.rcon_exec("ark", "10", "SaveWorld")["status"] == "success"
    assert api.get_runtime_status("ark", "10")["status"] == "success"
    assert api.check_update("ark", "10")["status"] == "success"
    assert api.discover_servers("ark")["status"] == "success"
    assert api.import_server("ark", {"install_path": "E:/GameServers/ark", "detected_map": "theisland_wp"})["status"] == "error"

    send_calls = [c for c in orch.calls if c[0] == "send_action"]
    assert send_calls == [
        ("send_action", "ark", "validate", {"instance_id": "10", "strict": True}),
        ("send_action", "ark", "install_deps", {"instance_id": "10"}),
        ("send_action", "ark", "rcon_exec", {"instance_id": "10", "command": "SaveWorld"}),
        ("send_action", "ark", "runtime_status", {"instance_id": "10"}),
        ("send_action", "ark", "check_update", {"instance_id": "10"}),
        ("send_action", "ark", "discover_servers", {}),
    ]


def test_adminapi_inspect_runtime_status_routes_to_explicit_plugin_probe():
    orch = _AdminOrchestratorStub()
    api = AdminAPI(orch)

    assert api.inspect_runtime_status("ark", "10")["status"] == "success"

    assert orch.calls == [
        ("send_action", "ark", "runtime_status", {"instance_id": "10"})
    ]


def test_adminapi_validate_plugin_supports_plugin_scoped_request():
    orch = _AdminOrchestratorStub()
    api = AdminAPI(orch)

    api.validate_plugin("ark", instance_id=None, strict=False)

    assert orch.calls == [
        ("send_action", "ark", "validate", {"instance_id": None, "strict": False})
    ]


def test_adminapi_install_server_prefers_orchestrator_method_then_falls_back_to_plugin_action():
    preferred = _PreferredInstallServerOrchestrator()
    api_preferred = AdminAPI(preferred)
    resp_preferred = api_preferred.install_server("ark", "10")
    assert resp_preferred["status"] == "success"
    assert preferred.calls == [("install_server_instance", "ark", "10")]

    fallback = _FallbackInstallServerOrchestrator()
    api_fallback = AdminAPI(fallback)
    resp_fallback = api_fallback.install_server("ark", "10")
    assert resp_fallback["status"] == "success"
    assert fallback.calls == [
        ("send_action", "ark", "install_server", {"instance_id": "10"})
    ]


def test_adminapi_check_update_prefers_orchestrator_method_then_falls_back_to_plugin_action():
    preferred = _PreferredCheckUpdateOrchestrator()
    api_preferred = AdminAPI(preferred)
    resp_preferred = api_preferred.check_update("ark", "10")
    assert resp_preferred["status"] == "success"
    assert preferred.calls == [("check_update", "ark", "10")]

    fallback = _FallbackInstallServerOrchestrator()
    api_fallback = AdminAPI(fallback)
    resp_fallback = api_fallback.check_update("ark", "10")
    assert resp_fallback["status"] == "success"
    assert fallback.calls == [
        ("send_action", "ark", "check_update", {"instance_id": "10"})
    ]


def test_adminapi_update_instance_prefers_orchestrator_method_then_falls_back_to_install_server():
    preferred = _PreferredUpdateInstanceOrchestrator()
    api_preferred = AdminAPI(preferred)
    resp_preferred = api_preferred.update_instance("ark", "10")
    assert resp_preferred["status"] == "success"
    assert preferred.calls == [("update_instance", "ark", "10")]

    fallback = _FallbackInstallServerOrchestrator()
    api_fallback = AdminAPI(fallback)
    resp_fallback = api_fallback.update_instance("ark", "10")
    assert resp_fallback["status"] == "success"
    assert fallback.calls == [
        ("send_action", "ark", "install_server", {"instance_id": "10"})
    ]


def test_adminapi_install_steamcmd_prefers_orchestrator_method_only():
    preferred = _PreferredInstallSteamcmdOrchestrator()
    api_preferred = AdminAPI(preferred)
    resp_preferred = api_preferred.install_steamcmd()
    assert resp_preferred["status"] == "success"
    assert preferred.calls == [("install_steamcmd",)]

    fallback = _FallbackInstallServerOrchestrator()
    api_fallback = AdminAPI(fallback)
    resp_fallback = api_fallback.install_steamcmd()
    assert resp_fallback["status"] == "error"
    assert "install_steamcmd" in resp_fallback["message"]


def test_adminapi_discover_servers_prefers_orchestrator_method_then_falls_back_to_plugin_action():
    preferred = _PreferredDiscoverServersOrchestrator()
    api_preferred = AdminAPI(preferred)
    resp_preferred = api_preferred.discover_servers("ark")
    assert resp_preferred["status"] == "success"
    assert preferred.calls == [("discover_servers", "ark")]

    fallback = _FallbackInstallServerOrchestrator()
    api_fallback = AdminAPI(fallback)
    resp_fallback = api_fallback.discover_servers("ark")
    assert resp_fallback["status"] == "success"
    assert fallback.calls == [
        ("send_action", "ark", "discover_servers", {})
    ]


def test_adminapi_import_server_prefers_orchestrator_method_only():
    preferred = _PreferredImportServerOrchestrator()
    api_preferred = AdminAPI(preferred)
    candidate = {"install_path": "E:/GameServers/ark", "detected_map": "theisland_wp"}
    resp_preferred = api_preferred.import_server("ark", candidate)
    assert resp_preferred["status"] == "success"
    assert preferred.calls == [("import_server", "ark", candidate)]

    fallback = _FallbackInstallServerOrchestrator()
    api_fallback = AdminAPI(fallback)
    resp_fallback = api_fallback.import_server("ark", candidate)
    assert resp_fallback["status"] == "error"
    assert "import_server" in resp_fallback["message"]

def test_adminapi_allocate_instance_ports_prefers_orchestrator_method_only():
    preferred = _PreferredAllocatePortsOrchestrator()
    api_preferred = AdminAPI(preferred)
    resp_preferred = api_preferred.allocate_instance_ports("ark")
    assert resp_preferred["status"] == "success"
    assert preferred.calls == [("allocate_instance_ports", "ark")]

    fallback = _FallbackInstallServerOrchestrator()
    api_fallback = AdminAPI(fallback)
    resp_fallback = api_fallback.allocate_instance_ports("ark")
    assert resp_fallback["status"] == "error"
    assert "allocate_instance_ports" in resp_fallback["message"]


def test_adminapi_suggest_next_instance_id_prefers_orchestrator_method_only():
    preferred = _PreferredNextInstanceIdOrchestrator()
    api_preferred = AdminAPI(preferred)
    resp_preferred = api_preferred.suggest_next_instance_id("ark")
    assert resp_preferred["status"] == "success"
    assert preferred.calls == [("suggest_next_instance_id", "ark")]

    fallback = _FallbackInstallServerOrchestrator()
    api_fallback = AdminAPI(fallback)
    resp_fallback = api_fallback.suggest_next_instance_id("ark")
    assert resp_fallback["status"] == "error"
    assert "suggest_next_instance_id" in resp_fallback["message"]


def test_adminapi_lifecycle_methods_route_to_orchestrator_authority_not_send_action():
    orch = _AdminOrchestratorStub()
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


def test_ark_plugin_unknown_action_fails_with_controlled_error(tmp_path):
    handler = _make_handler(tmp_path)

    resp = handler.handle("does_not_exist", {})

    assert resp["status"] == "error"
    assert "Unknown action" in resp["data"]["message"]


def test_e2e_harness_loads_through_generic_plugin_handler(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    reg = PluginRegistry(plugin_dir=str(repo_root / "plugins"), cluster_root=str(tmp_path))
    reg.load_all()

    loaded = reg.get("e2e_harness")
    assert isinstance(loaded, dict)
    assert isinstance(loaded.get("handler"), PluginHandler)


def test_ark_plugin_malformed_get_port_specs_fails_with_controlled_error(tmp_path):
    handler = _make_handler(tmp_path)

    resp = handler.handle("get_port_specs", {"requested_ports": ["not_an_int", "also_bad"]})

    assert resp["status"] == "error"
    assert resp["data"]["ok"] is False
    assert "requested_ports must be a list of ints" in resp["data"]["errors"]


def test_ark_plugin_get_port_specs_uses_plugin_json_roles(tmp_path):
    # PluginHandler uses required_ports from plugin.json (game=udp, rcon=tcp)
    handler = _make_handler(tmp_path)

    resp = handler.handle("get_port_specs", {"requested_ports": [7777, 27020]})

    assert resp["status"] == "success"
    assert resp["data"]["ports"] == [
        {"name": "game", "port": 7777, "proto": "udp"},
        {"name": "rcon", "port": 27020, "proto": "tcp"},
    ]

def test_adminapi_get_plugin_capabilities_reports_unknown_plugin():
    class _Registry:
        def get(self, name):
            return None

    orch = _AdminOrchestratorStub()
    orch._registry = _Registry()
    api = AdminAPI(orch)

    resp = api.get_plugin_capabilities("missing")
    assert resp["status"] == "error"
    assert "Unknown plugin" in resp["message"]




