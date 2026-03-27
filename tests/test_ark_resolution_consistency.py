import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.plugin_handler import PluginHandler


def _make_handler(tmp_path, defaults=None):
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
        cluster_root=str(tmp_path),
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


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only provisioning scope")
def test_resolution_consistency_across_validate_install_deps_install_server_and_start(
    tmp_path, monkeypatch
):
    gameservers_root = tmp_path / "GameServers"
    steamcmd_dir = tmp_path / "steamcmd"
    steamcmd_exe = steamcmd_dir / "steamcmd.exe"
    steamcmd_dir.mkdir(parents=True, exist_ok=True)
    steamcmd_exe.write_text("stub", encoding="utf-8")

    handler = _make_handler(
        tmp_path,
        defaults={
            "steamcmd_root": str(steamcmd_dir),
            "gameservers_root": str(gameservers_root),
            "admin_password": "pw",
        },
    )
    install_root = gameservers_root / "ArkSA" / "theisland_wp_1"
    _write_instance_config(
        tmp_path,
        "10",
        {
            "map": "theisland_wp",
            "game_port": 7777,
            "rcon_port": 27020,
            # Explicit install_root prevents suffix scan from returning a different
            # path after install_deps creates the directory.
            "install_root": str(install_root),
        },
    )

    # Spy on _resolve_layout to capture resolved paths for each action
    captured = []
    current_action = {"value": ""}
    original_resolve = handler._resolve_layout

    def spy_resolve(instance_id):
        layout = original_resolve(instance_id)
        if layout:
            captured.append(
                {
                    "action": current_action["value"],
                    "map_dir": layout.get("map_dir"),
                    "server_dir": layout.get("server_dir"),
                    "logs_dir": layout.get("logs_dir"),
                    "tmp_dir": layout.get("tmp_dir"),
                }
            )
        return layout

    handler._resolve_layout = spy_resolve

    class _FakeSteamProc:
        def __init__(self, argv, cwd=None, shell=False, stdout=None, stderr=None, startupinfo=None, **kwargs):
            if "+runscript" in argv:
                script_path = Path(argv[argv.index("+runscript") + 1])
                script_text = script_path.read_text(encoding="utf-8")
                target_line = [
                    line for line in script_text.splitlines()
                    if line.startswith("force_install_dir ")
                ][0]
                server_dir = Path(target_line.split('"', 2)[1])
                # Create server exe so start succeeds
                exe = server_dir / "ShooterGame" / "Binaries" / "Win64" / "ArkAscendedServer.exe"
                exe.parent.mkdir(parents=True, exist_ok=True)
                exe.write_text("stub", encoding="utf-8")
                if stdout is not None:
                    stdout.write("Loading Steam API...OK\n")
            self.returncode = 0

        def communicate(self, timeout=None):
            return ("", "")

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            pass

    class _FakeServerProc:
        def __init__(self, argv, cwd=None, shell=False, stdout=None, stderr=None,
                     startupinfo=None, creationflags=0, **kwargs):
            self.pid = 4242
            self.returncode = 0

        def poll(self):
            return None

        def communicate(self, timeout=None):
            return ("", "")

        def wait(self, timeout=None):
            return self.returncode

    def _fake_popen(argv, cwd=None, shell=False, stdout=None, stderr=None,
                    startupinfo=None, creationflags=0, **kwargs):
        if "+runscript" in argv:
            return _FakeSteamProc(argv, cwd=cwd, shell=shell, stdout=stdout,
                                  stderr=stderr, startupinfo=startupinfo)
        return _FakeServerProc(argv, cwd=cwd, shell=shell, stdout=stdout,
                               stderr=stderr, startupinfo=startupinfo,
                               creationflags=creationflags)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    def _send(action, payload):
        current_action["value"] = action
        return handler.handle(action, payload)

    validate_resp = _send("validate", {"instance_id": "10"})
    install_deps_resp = _send("install_deps", {"instance_id": "10"})
    install_server_resp = _send("install_server", {"instance_id": "10"})
    start_resp = _send("start", {"instance_id": "10"})

    assert validate_resp["status"] == "success", validate_resp
    assert install_deps_resp["status"] == "success", install_deps_resp
    assert install_server_resp["status"] == "success", install_server_resp
    assert start_resp["status"] == "success", start_resp

    # All 4 actions must have called _resolve_layout
    by_action = {item["action"]: item for item in captured}
    for action in ("validate", "install_deps", "install_server", "start"):
        assert action in by_action, f"Missing layout capture for action: {action}"

    # All actions resolved to the same paths
    reference = by_action["validate"]
    expected = (reference["map_dir"], reference["server_dir"], reference["logs_dir"], reference["tmp_dir"])
    for action in ("install_deps", "install_server", "start"):
        item = by_action[action]
        actual = (item["map_dir"], item["server_dir"], item["logs_dir"], item["tmp_dir"])
        assert actual == expected, f"{action} resolved different paths: {actual} != {expected}"
