"""
Smoke tests for PluginHandler using the real plugins/ark/plugin.json.

These verify the handler wires up correctly, not that the server actually starts.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from core.instance_layout import resolve_steam_game_master_layout


def _load_ark_plugin_json() -> dict:
    path = Path(__file__).resolve().parents[1] / "plugins" / "ark" / "plugin.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _make_handler(tmp_path, cluster_root=None):
    from core.plugin_handler import PluginHandler
    plugin_json = _load_ark_plugin_json()
    plugin_dir = str(tmp_path / "plugins" / "ark")
    Path(plugin_dir).mkdir(parents=True, exist_ok=True)
    return PluginHandler(plugin_json, plugin_dir, str(cluster_root or ""))


def test_plugin_handler_get_capabilities_returns_plugin_json(tmp_path):
    handler = _make_handler(tmp_path)
    result = handler.handle("get_capabilities", {})
    assert result.get("status") == "success"
    data = result.get("data") or {}
    assert data.get("game_id") == "ark_survival_ascended"
    assert data.get("name") == "ark"


def test_plugin_handler_shutdown_returns_ok(tmp_path):
    handler = _make_handler(tmp_path)
    result = handler.handle("shutdown", {})
    assert result == {"status": "success", "data": {"ok": True}}


def test_plugin_handler_unknown_action_returns_error(tmp_path):
    handler = _make_handler(tmp_path)
    result = handler.handle("not_a_real_action", {})
    assert result.get("status") == "error"
    assert "Unknown action" in str(result.get("data", {}).get("message", ""))


def test_plugin_handler_validate_missing_fields_returns_errors(tmp_path):
    handler = _make_handler(tmp_path, cluster_root=tmp_path)
    result = handler.handle("validate", {"instance_id": "test_instance"})
    assert result.get("status") in ("success", "error")
    data = result.get("data") or {}
    assert isinstance(data.get("checks"), list) or isinstance(data.get("errors"), list)


def test_plugin_handler_get_port_specs_returns_required_ports(tmp_path):
    handler = _make_handler(tmp_path)
    result = handler.handle("get_port_specs", {
        "requested_ports": [7777, 27020],
    })
    assert result.get("status") == "success"
    ports = (result.get("data") or {}).get("ports") or []
    assert len(ports) == 2
    names = {p["name"] for p in ports}
    assert "game" in names
    assert "rcon" in names
    game_port = next(p for p in ports if p["name"] == "game")
    rcon_port = next(p for p in ports if p["name"] == "rcon")
    assert game_port["port"] == 7777
    assert rcon_port["port"] == 27020


def test_resolve_steam_game_master_layout_defaults_under_hidden_ncc_tree():
    layout = resolve_steam_game_master_layout(
        {
            "gameservers_root": r"E:\GameServers",
            "steamcmd_root": r"E:\GameServers\steamcmd",
        },
        plugin_name="ark",
        default_install_folder="ArkSA",
    )

    assert layout["layout"] == "master"
    assert layout["is_master"] is True
    assert layout["install_root"] == r"E:\GameServers\.ncc\masters\ark\ArkSA"
    assert layout["logs_dir"] == r"E:\GameServers\.ncc\masters\ark\ArkSA\logs"


def test_plugin_handler_runtime_summary_includes_installed_version_from_install_log(tmp_path):
    handler = _make_handler(tmp_path, cluster_root=tmp_path)
    instance_id = "theisland"

    handler._build_monitor_kwargs = lambda iid: {
        "resolve_effective_layout_fn": lambda _iid: ({}, {}, {}),
        "resolve_effective_server_name_fn": lambda defaults, inst: "Server",
        "resolve_runtime_paths_fn": lambda layout, _iid: {
            "pid_file": str(tmp_path / "server.pid"),
            "server_log": str(tmp_path / "server.log"),
            "install_server_log": str(tmp_path / "install_server.log"),
        },
        "get_proc_fn": lambda _iid: None,
        "proc_is_running_fn": lambda proc: False,
        "read_pid_file_fn": lambda path: None,
        "tasklist_pid_running_fn": lambda pid: (False, None),
        "tasklist_first_ark_pid_fn": lambda: (None, None),
    }
    handler._tail_file_lines = lambda path, count: (
        True,
        ["Installed server version: 83.24"],
    ) if str(path).endswith("install_server.log") else (False, [])

    result = handler.handle("runtime_summary", {"instance_id": instance_id})

    assert result["status"] == "success"
    assert result["data"]["version"]["installed"] == "83.24"


def test_plugin_handler_runtime_summary_ignores_metadata_tokens_and_uses_server_log_version(tmp_path):
    handler = _make_handler(tmp_path, cluster_root=tmp_path)
    instance_id = "theisland"

    handler._build_monitor_kwargs = lambda iid: {
        "resolve_effective_layout_fn": lambda _iid: ({}, {}, {}),
        "resolve_effective_server_name_fn": lambda defaults, inst: "Server",
        "resolve_runtime_paths_fn": lambda layout, _iid: {
            "pid_file": str(tmp_path / "server.pid"),
            "server_log": str(tmp_path / "server.log"),
            "install_server_log": str(tmp_path / "install_server.log"),
        },
        "get_proc_fn": lambda _iid: None,
        "proc_is_running_fn": lambda proc: False,
        "read_pid_file_fn": lambda path: None,
        "tasklist_pid_running_fn": lambda pid: (False, None),
        "tasklist_first_ark_pid_fn": lambda: (None, None),
    }
    handler._tail_file_lines = lambda path, count: (
        True,
        ["steam_install - app_id=2430930", "returncode=0", "attempt=1"],
    ) if str(path).endswith("install_server.log") else (
        True,
        ["[2026.03.20-11.24.00] ARK Version: 83.24"],
    )

    result = handler.handle("runtime_summary", {"instance_id": instance_id})

    assert result["status"] == "success"
    assert result["data"]["version"]["installed"] is None
    assert result["data"]["version"]["running"] == "83.24"


def test_plugin_handler_runtime_summary_does_not_treat_generic_version_tokens_as_installed_version(tmp_path):
    instance_id = "10"
    handler = _make_handler(tmp_path, cluster_root=tmp_path)

    handler._build_monitor_kwargs = lambda iid: {
        "resolve_effective_layout_fn": lambda instance_id: ({}, {}, {}),
        "resolve_effective_server_name_fn": lambda defaults, inst: "Server",
        "resolve_runtime_paths_fn": lambda layout, instance_id: {
            "server_log": str(tmp_path / "server.log"),
            "install_server_log": str(tmp_path / "install_server.log"),
            "pid_file": str(tmp_path / "server.pid"),
        },
        "get_proc_fn": lambda instance_id: None,
        "proc_is_running_fn": lambda proc: False,
        "read_pid_file_fn": lambda path: None,
        "tasklist_pid_running_fn": lambda pid: False,
        "tasklist_first_ark_pid_fn": lambda: None,
    }
    handler._tail_file_lines = lambda path, n: (
        True,
        ["Steam Console Client (c) Valve Corporation - version 1773426366", "Version=7"],
    ) if str(path).endswith("install_server.log") else (
        True,
        ["Booting..."],
    )

    result = handler.handle("runtime_summary", {"instance_id": instance_id})

    assert result["status"] == "success"
    assert result["data"]["version"]["installed"] is None


def test_plugin_handler_runtime_summary_does_not_infer_running_from_unscoped_tasklist_probe(tmp_path):
    handler = _make_handler(tmp_path, cluster_root=tmp_path)
    instance_id = "theisland"

    handler._build_monitor_kwargs = lambda iid: {
        "resolve_effective_layout_fn": lambda _iid: ({}, {}, {}),
        "resolve_effective_server_name_fn": lambda defaults, inst: "Server",
        "resolve_runtime_paths_fn": lambda layout, _iid: {
            "pid_file": str(tmp_path / "server.pid"),
            "server_log": str(tmp_path / "server.log"),
            "install_server_log": str(tmp_path / "install_server.log"),
        },
        "get_proc_fn": lambda _iid: None,
        "proc_is_running_fn": lambda proc: False,
        "read_pid_file_fn": lambda path: None,
        "tasklist_pid_running_fn": lambda pid: (False, None),
        "tasklist_first_ark_pid_fn": lambda: (4321, None),
    }
    handler._tail_file_lines = lambda path, count: (False, [])

    result = handler.handle("runtime_summary", {"instance_id": instance_id})

    assert result["status"] == "success"
    assert result["data"]["running"] is False
    assert result["data"]["pid"] is None


def test_plugin_handler_check_update_includes_master_current_version_from_install_log(tmp_path, monkeypatch):
    handler = _make_handler(tmp_path, cluster_root=tmp_path)
    logs_dir = tmp_path / "master" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "install_server.log").write_text("Installed server version: 84.28\n", encoding="utf-8")

    handler._resolve_master_layout = lambda: {
        "install_root": str(tmp_path / "master"),
        "logs_dir": str(logs_dir),
        "steamcmd_dir": str(tmp_path / "steamcmd"),
    }
    handler._resolve_steamcmd_exe = lambda layout: str(tmp_path / "steamcmd" / "steamcmd.exe")
    handler._create_dirs = lambda layout: {"logs_dir": str(logs_dir)}
    handler._write_text_file = lambda path, text: None

    monkeypatch.setattr(
        "core.steam_installer.run_steamcmd_version_check",
        lambda **kwargs: ("22441125", []),
    )

    result = handler.handle("check_update", {"install_target": "master"})

    assert result["status"] == "success"
    assert result["data"]["target_version"] == "22441125"
    assert result["data"]["master_current_version"] == "84.28"


def test_plugin_handler_check_update_falls_back_to_master_executable_version_when_install_log_missing(tmp_path, monkeypatch):
    handler = _make_handler(tmp_path, cluster_root=tmp_path)
    logs_dir = tmp_path / "master" / "logs"
    server_dir = tmp_path / "master" / "ShooterGame" / "Binaries" / "Win64"
    logs_dir.mkdir(parents=True, exist_ok=True)
    server_dir.mkdir(parents=True, exist_ok=True)
    exe_path = server_dir / "ArkAscendedServer.exe"
    exe_path.write_text("", encoding="utf-8")

    handler._resolve_master_layout = lambda: {
        "install_root": str(tmp_path / "master"),
        "server_dir": str(tmp_path / "master"),
        "logs_dir": str(logs_dir),
        "steamcmd_dir": str(tmp_path / "steamcmd"),
    }
    handler._resolve_steamcmd_exe = lambda layout: str(tmp_path / "steamcmd" / "steamcmd.exe")
    handler._create_dirs = lambda layout: {"logs_dir": str(logs_dir), "server_dir": str(tmp_path / "master")}
    handler._write_text_file = lambda path, text: None
    handler._tail_file_lines = lambda path, count: (False, [])
    handler._read_executable_version = lambda path: "84.28"

    monkeypatch.setattr(
        "core.steam_installer.run_steamcmd_version_check",
        lambda **kwargs: ("22441125", []),
    )

    result = handler.handle("check_update", {"install_target": "master"})

    assert result["status"] == "success"
    assert result["data"]["target_version"] == "22441125"
    assert result["data"]["master_current_version"] == "84.28"


def test_plugin_handler_prepare_master_install_persists_trusted_master_build_state(tmp_path, monkeypatch):
    handler = _make_handler(tmp_path, cluster_root=tmp_path)
    logs_dir = tmp_path / "master" / "logs"
    server_dir = tmp_path / "master" / "ShooterGame" / "Binaries" / "Win64"
    logs_dir.mkdir(parents=True, exist_ok=True)
    server_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "install_server.log").write_text("Installed server version: 84.28\n", encoding="utf-8")
    exe_path = server_dir / "ArkAscendedServer.exe"
    exe_path.write_text("", encoding="utf-8")

    handler._resolve_master_layout = lambda: {
        "install_root": str(tmp_path / "master"),
        "server_dir": str(tmp_path / "master"),
        "logs_dir": str(logs_dir),
        "steamcmd_dir": str(tmp_path / "steamcmd"),
    }
    handler._resolve_steamcmd_exe = lambda layout: str(tmp_path / "steamcmd" / "steamcmd.exe")
    handler._create_dirs = lambda layout: {"logs_dir": str(logs_dir), "server_dir": str(tmp_path / "master")}
    handler._write_ini_settings = lambda instance_id, server_dir, field_names=None: []

    monkeypatch.setattr(
        "core.steam_installer.run_steamcmd_app_install",
        lambda **kwargs: {"ok": True, "warnings": [], "errors": []},
    )
    monkeypatch.setattr(
        "core.steam_installer.run_steamcmd_version_check",
        lambda **kwargs: ("22441125", []),
    )

    result = handler.handle("install_server", {"install_target": "master"})

    assert result["status"] == "success"
    state = json.loads((tmp_path / ".ncc" / "version_build_map.json").read_text(encoding="utf-8"))
    assert state["plugins"]["ark"]["master_current_build_id"] == "22441125"
    assert state["plugins"]["ark"].get("builds", {}) == {}


def test_plugin_handler_persist_trusted_master_build_state_does_not_overwrite_conflicting_mapping(tmp_path):
    handler = _make_handler(tmp_path, cluster_root=tmp_path)
    (tmp_path / ".ncc").mkdir(parents=True, exist_ok=True)
    state_path = tmp_path / ".ncc" / "version_build_map.json"
    state_path.write_text(
        json.dumps(
            {
                "plugins": {
                    "ark": {
                        "master_current_build_id": "22441125",
                        "builds": {
                            "22441125": "84.28",
                        },
                    }
                }
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    handler._load_version_build_state = lambda: json.loads(state_path.read_text(encoding="utf-8"))["plugins"]

    handler._persist_trusted_master_build_state("ark", "22441125", "84.29")

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["plugins"]["ark"]["master_current_build_id"] == "22441125"
    assert state["plugins"]["ark"]["builds"]["22441125"] == "84.28"


def test_plugin_handler_persist_trusted_master_build_state_uses_gameservers_root_map(tmp_path):
    handler = _make_handler(tmp_path, cluster_root=tmp_path)
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

    handler._persist_trusted_master_build_state("ark", "22441125", "84.28")

    state = json.loads((tmp_path / "GameServers" / ".ncc" / "version_build_map.json").read_text(encoding="utf-8"))
    assert state["plugins"]["ark"]["master_current_build_id"] == "22441125"
    assert state["plugins"]["ark"]["builds"]["22441125"] == "84.28"


def test_plugin_handler_start_builds_expected_launch_args(tmp_path, monkeypatch):
    from core.plugin_handler import PluginHandler

    plugin_json = _load_ark_plugin_json()
    plugin_dir = tmp_path / "plugins" / "ark"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gameservers_root": "D:/Ark",
                "install_root": "BriansPlayground",
                "cluster_id": "246246756",
                "mods": ["1022167"],
                "passive_mods": [],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "cluster_config.json").write_text(
        json.dumps({"gameservers_root": "D:/Ark"}),
        encoding="utf-8",
    )

    handler = PluginHandler(plugin_json, str(plugin_dir), str(tmp_path))
    instance_config = (
        tmp_path / "plugins" / "ark" / "instances" / "10" / "config" / "plugin_instance_config.json"
    )
    instance_config.parent.mkdir(parents=True, exist_ok=True)
    instance_config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "map": "theisland_WP",
                "game_port": 7777,
                "rcon_port": 27020,
                "mods": ["1315440"],
                "passive_mods": ["2234333"],
            }
        ),
        encoding="utf-8",
    )

    server_dir = tmp_path / "server"
    exe_path = server_dir / "ShooterGame" / "Binaries" / "Win64" / "ArkAscendedServer.exe"
    exe_path.parent.mkdir(parents=True, exist_ok=True)
    exe_path.write_text("stub", encoding="utf-8")
    handler._resolve_layout = lambda instance_id: {"server_dir": str(server_dir)}
    captured = {}

    class _Proc:
        pid = 4242

    def _fake_popen(argv, cwd=None, shell=False, creationflags=0, **kwargs):
        captured["argv"] = list(argv)
        captured["cwd"] = cwd
        captured["creationflags"] = creationflags
        return _Proc()

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    result = handler.handle("start", {"instance_id": "10"})

    assert result["status"] == "success"
    assert captured["argv"] == [
        str(exe_path),
        "theisland_WP",
        "-clusterID=246246756",
        "-ClusterDirOverride=D:/Ark/BriansPlayground/Cluster",
        "-mods=1022167,1315440",
        "-passivemods=2234333",
    ]


def test_plugin_handler_effective_server_name_uses_case_insensitive_friendly_map(tmp_path):
    handler = _make_handler(tmp_path, cluster_root=tmp_path)

    assert handler._effective_server_name({"map": "theisland_wp"}, {}) == "The Island"
    assert handler._effective_server_name({"display_name": "Brian Cluster", "map": "TheIsland_WP"}, {}) == "Brian Cluster The Island"
