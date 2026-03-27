from __future__ import annotations

from pathlib import Path
import json
import os
import shutil


from core.orchestrator import Orchestrator
from core.admin_api import AdminAPI
from core.state_manager import StateManager
from core.instance_layout import ensure_instance_layout, get_instance_root, read_instance_install_status, write_instance_install_status
from core.events import EVENT_INSTALL_STARTED, EVENT_INSTALL_COMPLETED, EVENT_INSTALL_FAILED


class FakeConn:
    def __init__(self, responses=None):
        self.requests = []
        self._responses = responses or {}

    def send_request(self, action, payload):
        self.requests.append((action, dict(payload or {})))
        if action in self._responses:
            return self._responses[action]
        if action == "sync_ini_fields":
            return {"status": "success", "data": {"ok": True, "warnings": [], "errors": []}}
        return {"status": "success"}



class SequencedFakeConn:
    def __init__(self, responses=None):
        self.requests = []
        self._responses = responses or {}

    def send_request(self, action, payload):
        self.requests.append((action, dict(payload or {})))
        scripted = self._responses.get(action)
        if isinstance(scripted, list):
            if scripted:
                return scripted.pop(0)
            if action == "sync_ini_fields":
                return {"status": "success", "data": {"ok": True, "warnings": [], "errors": []}}
            return {"status": "success"}
        if scripted is not None:
            return scripted
        if action == "sync_ini_fields":
            return {"status": "success", "data": {"ok": True, "warnings": [], "errors": []}}
        return {"status": "success"}
class FakeRegistry:
    def __init__(self, conn):
        self._conn = conn

    def load_all(self):
        return None

    def list_all(self):
        return ["ark"]

    def get(self, plugin_name):
        if plugin_name != "ark":
            return None
        return {"connection": self._conn, "process": None}

    def get_metadata(self, plugin_name):
        if plugin_name != "ark":
            return {}
        return {
            "name": "ark",
            "install_subfolder": "ArkSA",
            "executable": "ShooterGame\\Binaries\\Win64\\ArkAscendedServer.exe",
            "master_distribution_excludes": ["ShooterGame/Saved", "logs", "tmp"],
        }


class DependencyAwareRegistry(FakeRegistry):
    def get_metadata(self, plugin_name):
        if plugin_name != "ark":
            return {}
        return {
            "dependencies": [
                {
                    "id": "steamcmd",
                    "label": "SteamCMD",
                    "type": "app_config_path",
                    "field": "steamcmd_root",
                    "expected": "dir",
                    "guidance": {"action": "install_steamcmd", "label": "Install SteamCMD"},
                }
            ]
        }


def _read_meta(cluster_root: Path, plugin: str, instance: str) -> dict:
    meta_path = get_instance_root(str(cluster_root), plugin, instance) / "instance.json"
    return json.loads(meta_path.read_text(encoding="utf-8"))


def _write_meta(cluster_root: Path, plugin: str, instance: str, meta: dict) -> None:
    meta_path = get_instance_root(str(cluster_root), plugin, instance) / "instance.json"
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_start_refuses_when_not_installed(tmp_path: Path):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")

    conn = FakeConn()
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))

    # NOT_INSTALLED by default
    r = orch.start_instance("ark", "10")
    assert r["status"] == "error"
    assert "Run: install" in r["message"]

    # Must not have started plugin
    assert conn.requests == []

    # Must not have emitted install events (start is not allowed to auto-install)
    types = [e.get("event_type") for e in orch.get_events()]
    assert EVENT_INSTALL_STARTED not in types
    assert EVENT_INSTALL_COMPLETED not in types
    assert EVENT_INSTALL_FAILED not in types

    assert read_instance_install_status(str(cluster_root), "ark", "10") == "NOT_INSTALLED"


def test_install_sets_installed_and_does_not_start(tmp_path: Path):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")

    conn = FakeConn()
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))

    r = orch.install_instance("ark", "10")
    assert r["status"] == "success"
    assert r["install_status"] == "INSTALLED"

    # Install must not start server
    assert conn.requests == []

    # Events emitted
    types = [e.get("event_type") for e in orch.get_events()]
    assert EVENT_INSTALL_STARTED in types
    assert EVENT_INSTALL_COMPLETED in types

    assert read_instance_install_status(str(cluster_root), "ark", "10") == "INSTALLED"


def test_start_succeeds_after_install(tmp_path: Path):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")

    conn = FakeConn()
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))

    r1 = orch.install_instance("ark", "10")
    assert r1["status"] == "success"

    r2 = orch.start_instance("ark", "10")
    assert r2["status"] == "success"
    assert [action for action, _ in conn.requests] == ["start"]


def test_install_server_success_sets_installed_and_start_gate_passes(tmp_path: Path):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")

    conn = FakeConn(
        responses={
            "install_server": {
                "status": "success",
                "data": {"ok": True, "details": "install_server complete", "warnings": [], "errors": []},
            }
        }
    )
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))

    blocked = orch.start_instance("ark", "10")
    assert blocked["status"] == "error"
    assert "Instance not installed" in blocked["message"]

    install = orch.install_server_instance("ark", "10")
    assert install["status"] == "success"
    assert install["data"]["install_status"] == "INSTALLED"
    assert read_instance_install_status(str(cluster_root), "ark", "10") == "INSTALLED"

    started = orch.start_instance("ark", "10")
    assert started["status"] == "success"
    assert [a for a, _ in conn.requests].count("install_server") == 1
    assert conn.requests[-1][0] == "start"


def test_install_server_failure_sets_failed_and_start_still_refuses(tmp_path: Path):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")

    conn = FakeConn(
        responses={
            "install_server": {
                "status": "error",
                "data": {"ok": False, "details": "install_server failed", "warnings": [], "errors": ["boom"]},
            }
        }
    )
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))

    result = orch.install_server_instance("ark", "10")
    assert result["status"] == "error"
    assert result["data"]["install_status"] == "FAILED"
    assert read_instance_install_status(str(cluster_root), "ark", "10") == "FAILED"

    r2 = orch.start_instance("ark", "10")
    assert r2["status"] == "error"
    assert "Run: install" in r2["message"]


def test_install_server_fails_early_when_steamcmd_not_installed(tmp_path: Path):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")
    (cluster_root / "config").mkdir(parents=True, exist_ok=True)
    (cluster_root / "config" / "cluster_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "install_root_dir": str(cluster_root / "instances"),
                "backup_dir": str(cluster_root / "backups"),
                "cluster_name": "arkSA",
                "base_game_port": 30000,
                "base_rcon_port": 31000,
                "shared_mods": [],
                "shared_passive_mods": [],
                "instances": [],
                "gameservers_root": str(cluster_root / "GameServers"),
                "steamcmd_root": str(cluster_root / "steamcmd"),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    conn = FakeConn()
    reg = DependencyAwareRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))

    result = orch.install_server_instance("ark", "10")

    assert result["status"] == "error"
    assert result["data"]["install_status"] == "FAILED"
    assert "SteamCMD is not installed yet." in result["data"]["details"]
    assert str(cluster_root / "steamcmd") in result["data"]["details"]
    assert conn.requests == []
    assert read_instance_install_status(str(cluster_root), "ark", "10") == "FAILED"




def test_install_server_missing_ok_sets_failed(tmp_path: Path):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")

    conn = FakeConn(
        responses={
            "install_server": {
                "status": "success",
                "data": {"details": "missing ok"},
            }
        }
    )
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))

    result = orch.install_server_instance("ark", "10")
    assert result["data"]["install_status"] == "FAILED"
    assert read_instance_install_status(str(cluster_root), "ark", "10") == "FAILED"
    assert "install_server response data.ok must be true" in (result["data"].get("errors") or [])


def test_install_server_non_bool_ok_sets_failed(tmp_path: Path):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")

    conn = FakeConn(
        responses={
            "install_server": {
                "status": "success",
                "data": {"ok": "true", "details": "string bool"},
            }
        }
    )
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))

    result = orch.install_server_instance("ark", "10")
    assert result["data"]["install_status"] == "FAILED"
    assert read_instance_install_status(str(cluster_root), "ark", "10") == "FAILED"
    assert "install_server response data.ok must be true" in (result["data"].get("errors") or [])


def test_prepare_master_install_fails_early_when_steamcmd_not_installed(tmp_path: Path):
    cluster_root = tmp_path
    (cluster_root / "config").mkdir(parents=True, exist_ok=True)
    (cluster_root / "config" / "cluster_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cluster_name": "arkSA",
                "gameservers_root": str(cluster_root / "GameServers"),
                "steamcmd_root": str(cluster_root / "steamcmd"),
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    conn = FakeConn()
    reg = DependencyAwareRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))

    result = orch.prepare_master_install("ark")

    assert result["status"] == "error"
    assert "SteamCMD" in result["data"]["details"]
    assert conn.requests == []


def test_install_server_instance_prefers_prepared_master_distribution(tmp_path: Path, monkeypatch):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")
    plugin_dir = cluster_root / "plugins" / "ark"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gameservers_root": str(cluster_root / "GameServers"),
                "steamcmd_root": str(cluster_root / "steamcmd"),
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    instance_cfg = cluster_root / "plugins" / "ark" / "instances" / "10" / "config" / "plugin_instance_config.json"
    instance_cfg.parent.mkdir(parents=True, exist_ok=True)
    instance_cfg.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "map": "TheIsland_WP",
                "install_root": str(cluster_root / "GameServers" / "ArkSA" / "TheIsland_WP_1"),
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    master_root = cluster_root / "GameServers" / ".ncc" / "masters" / "ark" / "ArkSA"
    master_exe = master_root / "ShooterGame" / "Binaries" / "Win64" / "ArkAscendedServer.exe"
    master_exe.parent.mkdir(parents=True, exist_ok=True)
    master_exe.write_text("master-binary", encoding="utf-8")
    (master_root / "ShooterGame" / "Content" / "base.pak").parent.mkdir(parents=True, exist_ok=True)
    (master_root / "ShooterGame" / "Content" / "base.pak").write_text("pak", encoding="utf-8")
    (master_root / "ShooterGame" / "Saved" / "Config" / "WindowsServer" / "GameUserSettings.ini").parent.mkdir(parents=True, exist_ok=True)
    (master_root / "ShooterGame" / "Saved" / "Config" / "WindowsServer" / "GameUserSettings.ini").write_text("master", encoding="utf-8")

    dest_root = cluster_root / "GameServers" / "ArkSA" / "TheIsland_WP_1"
    preserved_ini = dest_root / "ShooterGame" / "Saved" / "Config" / "WindowsServer" / "GameUserSettings.ini"
    preserved_ini.parent.mkdir(parents=True, exist_ok=True)
    preserved_ini.write_text("instance", encoding="utf-8")

    conn = FakeConn()
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))
    orch._steamcmd_install_readiness_error = lambda plugin_name: None
    robocopy_calls = []

    def _fake_run(command, check=False, capture_output=True, text=True, shell=False):
        robocopy_calls.append(list(command))
        assert command[0].lower() == "robocopy"
        src = Path(command[1])
        dst = Path(command[2])
        excluded = {Path(item) for item in command[command.index("/XD") + 1:]} if "/XD" in command else set()
        for root, dirs, files in os.walk(src):
            root_path = Path(root)
            if any(root_path == item or item in root_path.parents for item in excluded):
                dirs[:] = []
                continue
            rel_root = root_path.relative_to(src)
            target_dir = dst / rel_root
            target_dir.mkdir(parents=True, exist_ok=True)
            for name in files:
                source_file = root_path / name
                if any(source_file == item or item in source_file.parents for item in excluded):
                    continue
                shutil.copy2(source_file, target_dir / name)

        class _Completed:
            returncode = 1
            stdout = ""
            stderr = ""

        return _Completed()

    monkeypatch.setattr("core.orchestrator.subprocess.run", _fake_run)

    result = orch.install_server_instance("ark", "10")

    assert result["status"] == "success"
    assert result["data"]["install_status"] == "INSTALLED"
    assert result["data"]["install_source"] == "master"
    assert result["data"]["distribution_method"] == "robocopy"
    assert conn.requests == []
    assert read_instance_install_status(str(cluster_root), "ark", "10") == "INSTALLED"
    assert (dest_root / "ShooterGame" / "Binaries" / "Win64" / "ArkAscendedServer.exe").read_text(encoding="utf-8") == "master-binary"
    assert (dest_root / "ShooterGame" / "Content" / "base.pak").read_text(encoding="utf-8") == "pak"
    assert preserved_ini.read_text(encoding="utf-8") == "instance"
    assert robocopy_calls != []
def test_forced_install_failure_sets_failed_and_start_still_refuses(tmp_path: Path):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")

    # Set force_install_fail in instance.json
    meta = _read_meta(cluster_root, "ark", "10")
    meta["force_install_fail"] = True
    _write_meta(cluster_root, "ark", "10", meta)

    conn = FakeConn()
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))

    r1 = orch.install_instance("ark", "10")
    assert r1["status"] == "error"
    assert read_instance_install_status(str(cluster_root), "ark", "10") == "FAILED"

    # Should have emitted failed event
    types = [e.get("event_type") for e in orch.get_events()]
    assert EVENT_INSTALL_FAILED in types

    # Start still refuses, and must not start plugin
    r2 = orch.start_instance("ark", "10")
    assert r2["status"] == "error"
    assert "Run: install" in r2["message"]
    assert conn.requests == []



def test_start_success_non_simulated_commits_running(tmp_path: Path):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")
    write_instance_install_status(str(cluster_root), "ark", "10", "INSTALLED")

    conn = FakeConn(
        responses={
            "start": {
                "status": "success",
                "data": {"ok": True, "simulated": False},
            }
        }
    )
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))

    resp = orch.start_instance("ark", "10")
    assert resp["status"] == "success"
    assert state.get_state("ark", "10") == state.RUNNING


def test_start_auto_updates_from_prepared_master_when_policy_enabled(tmp_path: Path, monkeypatch):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")
    write_instance_install_status(str(cluster_root), "ark", "10", "INSTALLED")
    plugin_dir = cluster_root / "plugins" / "ark"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "auto_update_on_restart": True,
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    conn = FakeConn(
        responses={
            "start": {"status": "success", "data": {"ok": True, "simulated": False}},
        }
    )
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))
    monkeypatch.setattr(
        orch,
        "check_update",
        lambda plugin_name, instance_id: {
            "status": "success",
            "data": {
                "ok": True,
                "update_available": True,
                "master_install_ready": True,
            },
        },
    )
    install_calls = []
    monkeypatch.setattr(
        orch,
        "install_server_instance",
        lambda plugin_name, instance_id: install_calls.append((plugin_name, instance_id)) or {"status": "success", "data": {"ok": True, "install_status": "INSTALLED"}},
    )
    orch._cached_runtime_summaries[("ark", "10")] = {
        "status": "success",
        "data": {"ok": True, "version": {"installed": "84.19", "running": "84.19"}},
    }

    resp = orch.start_instance("ark", "10")

    assert resp["status"] == "success"
    assert install_calls == [("ark", "10")]
    assert [action for action, _payload in conn.requests] == ["start", "runtime_summary"]


def test_start_success_simulated_does_not_commit_running(tmp_path: Path):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")
    write_instance_install_status(str(cluster_root), "ark", "10", "INSTALLED")

    conn = FakeConn(
        responses={
            "start": {
                "status": "success",
                "data": {"ok": True, "simulated": True},
            }
        }
    )
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))

    resp = orch.start_instance("ark", "10")
    assert resp["status"] == "success"
    assert state.get_state("ark", "10") == state.STOPPED


def test_start_failure_does_not_commit_running(tmp_path: Path):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")
    write_instance_install_status(str(cluster_root), "ark", "10", "INSTALLED")

    conn = FakeConn(
        responses={
            "start": {
                "status": "error",
                "data": {"ok": False, "simulated": False},
            }
        }
    )
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))

    resp = orch.start_instance("ark", "10")
    assert resp["status"] == "error"
    assert state.get_state("ark", "10") == state.STOPPED


def test_stop_success_non_simulated_stays_stopping_when_runtime_still_running(tmp_path: Path):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")

    conn = FakeConn(
        responses={
            "runtime_summary": {
                "status": "success",
                "data": {"ok": True, "running": True, "ready": False},
            },
            "graceful_stop": {
                "status": "success",
                "data": {"ok": True, "simulated": False},
            }
        }
    )
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))

    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.RUNNING)

    resp = orch.stop_instance("ark", "10")
    assert resp["status"] == "success"
    assert state.get_state("ark", "10") == state.STOPPING
    assert [a for a, _ in conn.requests].count("runtime_summary") == 2


def test_stop_failure_does_not_commit_stopped(tmp_path: Path):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")

    conn = FakeConn(
        responses={
            "runtime_summary": {
                "status": "success",
                "data": {"ok": True, "running": True, "ready": False},
            },
            "graceful_stop": {
                "status": "error",
                "data": {"ok": False, "simulated": False},
            }
        }
    )
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))

    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.RUNNING)

    resp = orch.stop_instance("ark", "10")
    assert resp["status"] == "error"
    assert state.get_state("ark", "10") == state.RUNNING



def test_stop_status_stays_stopping_while_runtime_running(tmp_path: Path):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")

    conn = SequencedFakeConn(
        responses={
            "runtime_summary": [
                {"status": "success", "data": {"ok": True, "running": True, "ready": False}},
                {"status": "success", "data": {"ok": True, "running": True, "ready": False}},
                {"status": "success", "data": {"ok": True, "running": True, "ready": False}},
                {"status": "success", "data": {"ok": True, "running": True, "ready": False}},
            ],
            "graceful_stop": {"status": "success", "data": {"ok": True, "simulated": False}},
        }
    )
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))
    api = AdminAPI(orch)

    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.RUNNING)

    _ = orch.stop_instance("ark", "10")
    snap = api.refresh_instance_status("ark", "10")
    assert snap["state"] == "STOPPING"


def test_stop_status_transitions_to_stopped_only_after_runtime_false(tmp_path: Path):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")

    conn = SequencedFakeConn(
        responses={
            "runtime_summary": [
                {"status": "success", "data": {"ok": True, "running": True, "ready": False}},
                {"status": "success", "data": {"ok": True, "running": True, "ready": False}},
                {"status": "success", "data": {"ok": True, "running": False, "ready": False}},
                {"status": "success", "data": {"ok": True, "running": False, "ready": False}},
            ],
            "graceful_stop": {"status": "success", "data": {"ok": True, "simulated": False}},
        }
    )
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))
    api = AdminAPI(orch)

    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.RUNNING)

    _ = orch.stop_instance("ark", "10")
    snap = api.refresh_instance_status("ark", "10")
    assert snap["state"] == "STOPPED"


def test_stop_timeout_forces_stop_and_commits_stopped(tmp_path: Path):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")

    conn = SequencedFakeConn(
        responses={
            "runtime_summary": [
                {"status": "success", "data": {"ok": True, "running": True, "ready": False}},
                {"status": "success", "data": {"ok": True, "running": True, "ready": False}},
                {"status": "success", "data": {"ok": True, "running": True, "ready": False}},
                {"status": "success", "data": {"ok": True, "running": False, "ready": False}},
                {"status": "success", "data": {"ok": True, "running": False, "ready": False}},
            ],
            "graceful_stop": {"status": "success", "data": {"ok": True, "simulated": False}},
            "stop": {"status": "success", "data": {"ok": True, "simulated": False}},
        }
    )
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))
    api = AdminAPI(orch)

    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.RUNNING)

    _ = orch.stop_instance("ark", "10")
    orch._stop_deadlines[("ark", "10")] = orch._now() - 1.0

    snap = api.refresh_instance_status("ark", "10")
    assert snap["state"] == "STOPPED"
    assert any(a == "stop" for a, _ in conn.requests)



def test_update_instance_stopped_uses_existing_install_server_path(tmp_path: Path):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")

    conn = FakeConn(
        responses={
            "runtime_summary": {"status": "success", "data": {"ok": True, "running": False, "ready": False}},
            "install_server": {"status": "success", "data": {"ok": True, "details": "install_server complete", "warnings": [], "errors": []}},
        }
    )
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))
    orch._cached_runtime_summaries[("ark", "10")] = {
        "status": "success",
        "data": {"ok": True, "version": {"installed": "84.19", "running": "84.19"}},
    }

    result = orch.update_instance("ark", "10")

    assert result["status"] == "success"
    assert [action for action, _ in conn.requests] == ["runtime_summary", "install_server"]


def test_update_instance_running_warns_stops_installs_and_starts(tmp_path: Path, monkeypatch):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")
    plugin_dir = cluster_root / "plugins" / "ark"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mods": [],
                "passive_mods": [],
                "update_warning_minutes": 2,
                "update_warning_interval_minutes": 1,
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    conn = SequencedFakeConn(
        responses={
            "runtime_summary": [
                {"status": "success", "data": {"ok": True, "running": True, "ready": True}},
                {"status": "success", "data": {"ok": True, "running": True, "ready": False}},
                {"status": "success", "data": {"ok": True, "running": False, "ready": False}},
            ],
            "rcon_exec": {"status": "success", "data": {"ok": True, "details": "rcon ok", "warnings": [], "errors": []}},
            "graceful_stop": {"status": "success", "data": {"ok": True, "simulated": False}},
            "install_server": {"status": "success", "data": {"ok": True, "details": "install_server complete", "warnings": [], "errors": []}},
            "start": {"status": "success", "data": {"ok": True, "simulated": False, "details": "start complete"}},
        }
    )
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))
    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.RUNNING)
    monkeypatch.setattr(orch, "_stored_master_build_for_plugin", lambda plugin_name: None)
    orch._cached_runtime_summaries[("ark", "10")] = {
        "status": "success",
        "data": {"ok": True, "version": {"installed": "84.19", "running": "84.19"}},
    }

    sleeps = []
    monkeypatch.setattr("core.orchestrator.time.sleep", lambda seconds: sleeps.append(seconds))

    result = orch.update_instance("ark", "10")

    assert result["status"] == "success"
    assert [action for action, _ in conn.requests] == [
        "runtime_summary",
        "rcon_exec",
        "rcon_exec",
        "runtime_summary",
        "graceful_stop",
        "runtime_summary",
        "runtime_summary",
        "install_server",
        "start",
        "runtime_summary",
    ]
    assert conn.requests[1][1]["command"] == "ServerChat Server update in 2 minutes. Please prepare to disconnect."
    assert conn.requests[2][1]["command"] == "ServerChat Server update in 1 minute. Please prepare to disconnect."
    assert sleeps == [60.0, 60.0]
    assert state.get_state("ark", "10") == state.RUNNING


def test_update_instance_persists_verified_build_mapping_after_started_server_reports_newer_version(tmp_path: Path, monkeypatch):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")
    (cluster_root / ".ncc").mkdir(parents=True, exist_ok=True)
    (cluster_root / ".ncc" / "version_build_map.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "ark": {
                        "master_current_build_id": "22441125",
                    }
                }
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    conn = SequencedFakeConn(responses={})
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))
    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.RUNNING)
    monkeypatch.setattr(orch, "_load_update_policy", lambda plugin_name: {"warning_minutes": 0, "interval_minutes": 0})
    monkeypatch.setattr(orch, "_stored_master_build_for_plugin", lambda plugin_name: "22441125")
    runtime_states = iter([True, False])
    monkeypatch.setattr(orch, "_runtime_running", lambda plugin_name, instance_id: next(runtime_states))
    monkeypatch.setattr(
        orch,
        "stop_instance",
        lambda plugin_name, instance_id: (
            state.set_state(plugin_name, instance_id, state.STOPPED) or {"status": "success", "data": {"ok": True}}
        ),
    )
    monkeypatch.setattr(
        orch,
        "install_server_instance",
        lambda plugin_name, instance_id: {
            "status": "success",
            "data": {
                "ok": True,
                "details": "install_server complete",
                "warnings": [],
                "errors": [],
                "master_install_root": str(cluster_root / "GameServers" / ".ncc" / "masters" / "ark" / "ArkSA"),
                "install_root": str(cluster_root / "GameServers" / "ArkSA" / "TheIsland_WP_1"),
            },
        },
    )
    monkeypatch.setattr(orch, "get_instance_install_status", lambda plugin_name, instance_id: "INSTALLED")
    orch._cached_runtime_summaries[("ark", "10")] = {
        "status": "success",
        "data": {"ok": True, "version": {"installed": "84.19", "running": "84.19"}},
    }
    monkeypatch.setattr(
        orch,
        "send_action",
        lambda plugin_name, action, payload=None: (
            {"status": "success", "data": {"ok": True, "simulated": False, "details": "start complete"}}
            if str(action) == "start"
            else {"status": "success", "data": {"ok": True, "running": True, "ready": True, "version": {"installed": "84.28", "running": "84.28"}}}
        ),
    )

    result = orch.update_instance("ark", "10")
    refreshed = orch.refresh_runtime_summary("ark", "10")

    assert result["status"] == "success"
    assert refreshed["status"] == "success"
    stored = json.loads((cluster_root / ".ncc" / "version_build_map.json").read_text(encoding="utf-8"))
    assert stored["plugins"]["ark"]["master_current_build_id"] == "22441125"
    assert stored["plugins"]["ark"]["builds"]["22441125"] == "84.28"


def test_update_instance_fails_when_started_server_version_does_not_advance(tmp_path: Path, monkeypatch):
    cluster_root = tmp_path
    ensure_instance_layout(str(cluster_root), "ark", "10")
    (cluster_root / ".ncc").mkdir(parents=True, exist_ok=True)
    (cluster_root / ".ncc" / "version_build_map.json").write_text(
        json.dumps(
            {
                "plugins": {
                    "ark": {
                        "master_current_build_id": "22441125",
                    }
                }
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )

    conn = SequencedFakeConn(responses={})
    reg = FakeRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=str(cluster_root))
    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.RUNNING)
    monkeypatch.setattr(orch, "_load_update_policy", lambda plugin_name: {"warning_minutes": 0, "interval_minutes": 0})
    monkeypatch.setattr(orch, "_stored_master_build_for_plugin", lambda plugin_name: "22441125")
    runtime_states = iter([True, False])
    monkeypatch.setattr(orch, "_runtime_running", lambda plugin_name, instance_id: next(runtime_states))
    monkeypatch.setattr(
        orch,
        "stop_instance",
        lambda plugin_name, instance_id: (
            state.set_state(plugin_name, instance_id, state.STOPPED) or {"status": "success", "data": {"ok": True}}
        ),
    )
    monkeypatch.setattr(
        orch,
        "install_server_instance",
        lambda plugin_name, instance_id: {
            "status": "success",
            "data": {
                "ok": True,
                "details": "install_server complete",
                "warnings": [],
                "errors": [],
                "master_install_root": str(cluster_root / "GameServers" / ".ncc" / "masters" / "ark" / "ArkSA"),
                "install_root": str(cluster_root / "GameServers" / "ArkSA" / "TheIsland_WP_1"),
            },
        },
    )
    monkeypatch.setattr(orch, "get_instance_install_status", lambda plugin_name, instance_id: "INSTALLED")
    orch._cached_runtime_summaries[("ark", "10")] = {
        "status": "success",
        "data": {"ok": True, "version": {"installed": "84.19", "running": "84.19"}},
    }
    monkeypatch.setattr(
        orch,
        "send_action",
        lambda plugin_name, action, payload=None: (
            {"status": "success", "data": {"ok": True, "simulated": False, "details": "start complete"}}
            if str(action) == "start"
            else {"status": "success", "data": {"ok": True, "running": True, "ready": True, "version": {"installed": "84.19", "running": "84.19"}}}
        ),
    )

    result = orch.update_instance("ark", "10")
    refreshed = orch.refresh_runtime_summary("ark", "10")

    assert result["status"] == "error"
    assert "Update verification failed for ark 10" in result["message"]
    assert refreshed["status"] == "success"
    stored = json.loads((cluster_root / ".ncc" / "version_build_map.json").read_text(encoding="utf-8"))
    assert stored["plugins"]["ark"]["master_current_build_id"] == "22441125"
    assert stored["plugins"]["ark"].get("builds", {}) == {}
