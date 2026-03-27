import json
from pathlib import Path

from core.admin_api import AdminAPI
from core.orchestrator import Orchestrator
from core.state_manager import StateManager


class _ImportConn:
    def __init__(self):
        self.requests = []

    def send_request(self, action, payload):
        payload = dict(payload or {})
        self.requests.append((str(action), payload))
        if str(action) == "get_port_specs":
            requested = list(payload.get("requested_ports") or [])
            game_port = int(requested[0])
            rcon_port = int(requested[1])
            return {
                "status": "success",
                "data": {
                    "ok": True,
                    "ports": [
                        {"name": "game", "port": game_port, "proto": "udp"},
                        {"name": "rcon", "port": rcon_port, "proto": "tcp"},
                    ],
                },
            }
        return {"status": "success", "data": {"ok": True}}


class _Registry:
    def __init__(self, conn):
        self._conn = conn

    def get(self, plugin_name):
        if str(plugin_name) != "ark":
            return None
        return {"connection": self._conn, "process": None}

    def list_all(self):
        return ["ark"]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_import_server_creates_next_available_instance_with_detected_values(tmp_path):
    conn = _ImportConn()
    orch = Orchestrator(_Registry(conn), StateManager(state_file=None), cluster_root=str(tmp_path))
    api = AdminAPI(orch)

    api.add_instance("ark", "1")
    api.add_instance("ark", "3")

    install_root = tmp_path / "GameServers" / "clusters" / "arkSA" / "theisland_wp"
    install_root.mkdir(parents=True, exist_ok=True)

    resp = api.import_server(
        "ark",
        {
            "install_path": str(install_root),
            "detected_map": "theisland_wp",
            "ports": [
                {"name": "game", "port": 7777, "proto": "udp"},
                {"name": "rcon", "port": 27020, "proto": "tcp"},
            ],
            "ini_fields": {
                "game_port": 7777,
                "rcon_port": 27020,
                "server_name": "The Island Prime",
                "admin_password": "topsecret",
                "rcon_enabled": True,
                "mods": ["111", "222"],
                "passive_mods": ["333"],
                "max_players": 20,
            },
            "managed_match": False,
        },
    )

    assert resp["status"] == "success"
    data = resp["data"]
    assert data["instance_id"] == "2"
    assert data["detected_map"] == "theisland_wp"
    assert data["install_root"] == str(install_root)
    assert data["game_port"] == 7777
    assert data["rcon_port"] == 27020

    config_path = tmp_path / "plugins" / "ark" / "instances" / "2" / "config" / "instance_config.json"
    config = _read_json(config_path)
    assert config["map"] == "theisland_wp"
    assert config["install_root"] == str(install_root)
    assert config["game_port"] == 7777
    assert config["rcon_port"] == 27020
    assert config["server_name"] == "The Island Prime"
    assert config["admin_password"] == "topsecret"
    assert config["rcon_enabled"] is True
    assert config["mods"] == ["111", "222"]
    assert config["passive_mods"] == ["333"]
    assert config["max_players"] == 20
    assert config["ports"] == [
        {"name": "game", "port": 7777, "proto": "udp"},
        {"name": "rcon", "port": 27020, "proto": "tcp"},
    ]
    assert orch.get_instance_state("ark", "2") == orch._state_manager.STOPPED
    assert orch.get_instance_install_status("ark", "2") == "INSTALLED"


def test_import_server_falls_back_to_deterministic_default_ports_when_missing(tmp_path):
    conn = _ImportConn()
    orch = Orchestrator(_Registry(conn), StateManager(state_file=None), cluster_root=str(tmp_path))
    api = AdminAPI(orch)

    install_root = tmp_path / "LegacyArk"
    install_root.mkdir(parents=True, exist_ok=True)

    resp = api.import_server(
        "ark",
        {
            "install_path": str(install_root),
            "detected_map": "thecenter_wp",
            "ports": [],
            "managed_match": False,
        },
    )

    assert resp["status"] == "success"
    data = resp["data"]
    assert data["instance_id"] == "1"
    assert data["game_port"] == 30000
    assert data["rcon_port"] == 31000
    assert ("get_port_specs", {"requested_ports": [30000, 31000]}) in conn.requests

    config_path = tmp_path / "plugins" / "ark" / "instances" / "1" / "config" / "instance_config.json"
    config = _read_json(config_path)
    assert config["install_root"] == str(install_root)
    assert config["game_port"] == 30000
    assert config["rcon_port"] == 31000
    assert config["ports"] == [
        {"name": "game", "port": 30000, "proto": "udp"},
        {"name": "rcon", "port": 31000, "proto": "tcp"},
    ]


def test_import_server_rejects_candidate_already_managed(tmp_path):
    conn = _ImportConn()
    orch = Orchestrator(_Registry(conn), StateManager(state_file=None), cluster_root=str(tmp_path))
    api = AdminAPI(orch)

    resp = api.import_server(
        "ark",
        {
            "install_path": str(tmp_path / "GameServers" / "clusters" / "arkSA" / "theisland_wp"),
            "detected_map": "theisland_wp",
            "managed_match": True,
        },
    )

    assert resp["status"] == "error"
    assert "already matches" in resp["message"]

def test_import_server_allocates_next_policy_pair_when_managed_ports_are_used(tmp_path):
    conn = _ImportConn()
    orch = Orchestrator(_Registry(conn), StateManager(state_file=None), cluster_root=str(tmp_path))
    api = AdminAPI(orch)

    api.add_instance("ark", "1")
    configured = orch.configure_instance_config(
        plugin_name="ark",
        instance_id="1",
        map_name="TheIsland_WP",
        game_port=30000,
        rcon_port=31000,
        mods=[],
        passive_mods=[],
        map_mod=None,
    )
    assert configured["status"] == "success"

    install_root = tmp_path / "LegacyArk2"
    install_root.mkdir(parents=True, exist_ok=True)

    resp = api.import_server(
        "ark",
        {
            "install_path": str(install_root),
            "detected_map": "thecenter_wp",
            "ports": [],
            "managed_match": False,
        },
    )

    assert resp["status"] == "success"
    data = resp["data"]
    assert data["instance_id"] == "2"
    assert data["game_port"] == 30002
    assert data["rcon_port"] == 31001
    assert ("get_port_specs", {"requested_ports": [30002, 31001]}) in conn.requests


def test_import_server_reassigns_discovered_ports_when_candidate_pair_conflicts_with_managed_instance(tmp_path):
    conn = _ImportConn()
    orch = Orchestrator(_Registry(conn), StateManager(state_file=None), cluster_root=str(tmp_path))
    api = AdminAPI(orch)

    api.add_instance("ark", "1")
    configured = orch.configure_instance_config(
        plugin_name="ark",
        instance_id="1",
        map_name="TheIsland_WP",
        game_port=7778,
        rcon_port=27020,
        mods=[],
        passive_mods=[],
        map_mod=None,
    )
    assert configured["status"] == "success"

    install_root = tmp_path / "LegacyArk3"
    install_root.mkdir(parents=True, exist_ok=True)

    resp = api.import_server(
        "ark",
        {
            "install_path": str(install_root),
            "detected_map": "thecenter_wp",
            "ports": [
                {"name": "game", "port": 7778, "proto": "udp"},
                {"name": "rcon", "port": 27020, "proto": "tcp"},
            ],
            "managed_match": False,
        },
    )

    assert resp["status"] == "success"
    data = resp["data"]
    assert data["game_port"] == 30000
    assert data["rcon_port"] == 31000


def test_import_server_overwrites_discovered_admin_password_with_managed_default(tmp_path):
    conn = _ImportConn()
    orch = Orchestrator(_Registry(conn), StateManager(state_file=None), cluster_root=str(tmp_path))
    api = AdminAPI(orch)

    plugin_defaults = tmp_path / "plugins" / "ark" / "plugin_defaults.json"
    plugin_defaults.parent.mkdir(parents=True, exist_ok=True)
    plugin_defaults.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "admin_password": "managed-secret",
                "rcon_enabled": True,
            }
        ),
        encoding="utf-8",
    )

    install_root = tmp_path / "ImportedArkManaged"
    install_root.mkdir(parents=True, exist_ok=True)

    resp = api.import_server(
        "ark",
        {
            "install_path": str(install_root),
            "detected_map": "theisland_wp",
            "ports": [
                {"name": "game", "port": 7777, "proto": "udp"},
                {"name": "rcon", "port": 27020, "proto": "tcp"},
            ],
            "ini_fields": {
                "admin_password": "legacy-secret",
                "rcon_enabled": False,
            },
            "managed_match": False,
        },
    )

    assert resp["status"] == "success"
    config_path = tmp_path / "plugins" / "ark" / "instances" / "1" / "config" / "instance_config.json"
    config = _read_json(config_path)
    assert config["admin_password"] == "managed-secret"
    assert config["rcon_enabled"] is True


def test_import_server_dedupes_imported_mods_against_plugin_defaults(tmp_path):
    conn = _ImportConn()
    orch = Orchestrator(_Registry(conn), StateManager(state_file=None), cluster_root=str(tmp_path))
    api = AdminAPI(orch)

    plugin_defaults = tmp_path / "plugins" / "ark" / "plugin_defaults.json"
    plugin_defaults.parent.mkdir(parents=True, exist_ok=True)
    plugin_defaults.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mods": ["111"],
                "passive_mods": ["333"],
            }
        ),
        encoding="utf-8",
    )

    install_root = tmp_path / "ImportedArk"
    install_root.mkdir(parents=True, exist_ok=True)

    resp = api.import_server(
        "ark",
        {
            "install_path": str(install_root),
            "detected_map": "theisland_wp",
            "ports": [
                {"name": "game", "port": 7777, "proto": "udp"},
                {"name": "rcon", "port": 27020, "proto": "tcp"},
            ],
            "ini_fields": {
                "mods": ["111", "222"],
                "passive_mods": ["333", "444"],
            },
            "managed_match": False,
        },
    )

    assert resp["status"] == "success"
    config_path = tmp_path / "plugins" / "ark" / "instances" / "1" / "config" / "instance_config.json"
    config = _read_json(config_path)
    assert config["mods"] == ["222"]
    assert config["passive_mods"] == ["444"]
