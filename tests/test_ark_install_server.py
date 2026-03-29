import json
import subprocess
import sys
from pathlib import Path

import pytest

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


class _FakeSteamCmdProc:
    """Fake SteamCMD that reads the runscript and creates the exe in the target dir."""

    def __init__(self, argv, cwd=None, shell=False, stdout=None, stderr=None, startupinfo=None, **kwargs):
        if "+runscript" in argv:
            script_path = Path(argv[argv.index("+runscript") + 1])
            script_text = script_path.read_text(encoding="utf-8")
            target_line = [
                line for line in script_text.splitlines()
                if line.startswith("force_install_dir ")
            ][0]
            server_dir = Path(target_line.split('"', 2)[1])
            server_dir.mkdir(parents=True, exist_ok=True)
            exe = server_dir / "ShooterGame" / "Binaries" / "Win64" / "ArkAscendedServer.exe"
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_text("stub", encoding="utf-8")
        self.stdout = _FakeStdout("Loading Steam API...OK\n")
        self.returncode = 0

    def poll(self):
        if self.stdout.done:
            return self.returncode
        return None

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        pass


class _FakeStdout:
    def __init__(self, text: str):
        self._lines = [line + "\n" for line in str(text or "").splitlines()]
        self._index = 0

    @property
    def done(self):
        return self._index >= len(self._lines)

    def readline(self):
        if self.done:
            return ""
        value = self._lines[self._index]
        self._index += 1
        return value

    def read(self):
        if self.done:
            return ""
        value = "".join(self._lines[self._index :])
        self._index = len(self._lines)
        return value

    def close(self):
        return None


class _FakeSteamCmdFailProc:
    def __init__(self, argv, cwd=None, shell=False, stdout=None, stderr=None, startupinfo=None, **kwargs):
        self.stdout = _FakeStdout("line1\nline2\n")
        self.returncode = 8

    def poll(self):
        if self.stdout.done:
            return self.returncode
        return None

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        pass


class _FakeSteamCmdFatalProc:
    def __init__(self, argv, cwd=None, shell=False, stdout=None, stderr=None, startupinfo=None, **kwargs):
        self.stdout = _FakeStdout("Loading Steam API...OK\nERROR! Failed to install app '2430930'\n")
        self.returncode = 0

    def poll(self):
        if self.stdout.done:
            return self.returncode
        return None

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        pass


class _FakeSteamCmdTimeoutProc:
    def __init__(self, argv, cwd=None, shell=False, stdout=None, stderr=None, startupinfo=None, **kwargs):
        class _TimeoutStdout:
            def readline(self_inner):
                raise subprocess.TimeoutExpired(cmd=["steamcmd.exe"], timeout=1)

            def read(self_inner):
                return ""

            def close(self_inner):
                return None

        self.stdout = _TimeoutStdout()
        self.returncode = None

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only provisioning scope")
def test_install_server_success_returns_ok(tmp_path, monkeypatch):
    steamcmd_dir = tmp_path / "steamcmd"
    steamcmd_exe = steamcmd_dir / "steamcmd.exe"
    steamcmd_dir.mkdir(parents=True, exist_ok=True)
    steamcmd_exe.write_text("stub", encoding="utf-8")

    handler = _make_handler(
        tmp_path,
        defaults={
            "steamcmd_root": str(steamcmd_dir),
            "gameservers_root": str(tmp_path / "GameServers"),
        },
    )
    _write_instance_config(tmp_path, "10", {"map": "theisland_wp"})

    monkeypatch.setattr(subprocess, "Popen", _FakeSteamCmdProc)

    resp = handler.handle("install_server", {"instance_id": "10"})

    assert resp["status"] == "success"
    assert resp["data"]["ok"] is True
    assert resp["data"]["errors"] == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only provisioning scope")
def test_install_server_creates_runscript_with_correct_app_id(tmp_path, monkeypatch):
    steamcmd_dir = tmp_path / "steamcmd"
    steamcmd_exe = steamcmd_dir / "steamcmd.exe"
    steamcmd_dir.mkdir(parents=True, exist_ok=True)
    steamcmd_exe.write_text("stub", encoding="utf-8")

    handler = _make_handler(
        tmp_path,
        defaults={
            "steamcmd_root": str(steamcmd_dir),
            "gameservers_root": str(tmp_path / "GameServers"),
        },
    )
    _write_instance_config(tmp_path, "10", {"map": "theisland_wp"})

    captured_argv = []

    class _CapturePopen(_FakeSteamCmdProc):
        def __init__(self, argv, **kwargs):
            captured_argv.extend(argv)
            super().__init__(argv, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", _CapturePopen)

    handler.handle("install_server", {"instance_id": "10"})

    # Verify runscript contains correct steam_app_id from plugin.json
    runscript_arg_idx = captured_argv.index("+runscript") + 1
    runscript_content = Path(captured_argv[runscript_arg_idx]).read_text(encoding="utf-8")
    assert "app_update 2430930 validate" in runscript_content
    assert "login anonymous" in runscript_content


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only provisioning scope")
def test_install_server_fails_without_steamcmd_configured(tmp_path):
    # No steamcmd_root in defaults → steamcmd_dir is None → error
    handler = _make_handler(
        tmp_path,
        defaults={"gameservers_root": str(tmp_path / "GameServers")},
    )
    _write_instance_config(tmp_path, "10", {"map": "theisland_wp"})

    resp = handler.handle("install_server", {"instance_id": "10"})

    assert resp["status"] == "error"
    assert resp["data"]["ok"] is False
    assert any("SteamCMD" in e for e in resp["data"]["errors"])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only provisioning scope")
def test_install_server_fails_when_steamcmd_exe_missing(tmp_path):
    steamcmd_dir = tmp_path / "steamcmd"
    steamcmd_dir.mkdir(parents=True, exist_ok=True)
    # Dir exists but steamcmd.exe not present

    handler = _make_handler(
        tmp_path,
        defaults={
            "steamcmd_root": str(steamcmd_dir),
            "gameservers_root": str(tmp_path / "GameServers"),
        },
    )
    _write_instance_config(tmp_path, "10", {"map": "theisland_wp"})

    resp = handler.handle("install_server", {"instance_id": "10"})

    assert resp["status"] == "error"
    assert resp["data"]["ok"] is False
    assert any("SteamCMD" in e for e in resp["data"]["errors"])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only provisioning scope")
def test_install_server_nonzero_exit_returns_error(tmp_path, monkeypatch):
    steamcmd_dir = tmp_path / "steamcmd"
    steamcmd_exe = steamcmd_dir / "steamcmd.exe"
    steamcmd_dir.mkdir(parents=True, exist_ok=True)
    steamcmd_exe.write_text("stub", encoding="utf-8")

    handler = _make_handler(
        tmp_path,
        defaults={
            "steamcmd_root": str(steamcmd_dir),
            "gameservers_root": str(tmp_path / "GameServers"),
        },
    )
    _write_instance_config(tmp_path, "10", {"map": "theisland_wp"})

    monkeypatch.setattr(subprocess, "Popen", _FakeSteamCmdFailProc)

    resp = handler.handle("install_server", {"instance_id": "10"})

    assert resp["status"] == "error"
    assert resp["data"]["ok"] is False
    assert any("exit code" in e.lower() for e in resp["data"]["errors"])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only provisioning scope")
def test_install_server_fatal_log_marker_returns_error(tmp_path, monkeypatch):
    steamcmd_dir = tmp_path / "steamcmd"
    steamcmd_exe = steamcmd_dir / "steamcmd.exe"
    steamcmd_dir.mkdir(parents=True, exist_ok=True)
    steamcmd_exe.write_text("stub", encoding="utf-8")

    handler = _make_handler(
        tmp_path,
        defaults={
            "steamcmd_root": str(steamcmd_dir),
            "gameservers_root": str(tmp_path / "GameServers"),
        },
    )
    _write_instance_config(tmp_path, "10", {"map": "theisland_wp"})

    monkeypatch.setattr(subprocess, "Popen", _FakeSteamCmdFatalProc)

    resp = handler.handle("install_server", {"instance_id": "10"})

    assert resp["status"] == "error"
    assert resp["data"]["ok"] is False
    assert any("failed to install app" in e.lower() for e in resp["data"]["errors"])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only provisioning scope")
def test_install_server_timeout_returns_error(tmp_path, monkeypatch):
    steamcmd_dir = tmp_path / "steamcmd"
    steamcmd_exe = steamcmd_dir / "steamcmd.exe"
    steamcmd_dir.mkdir(parents=True, exist_ok=True)
    steamcmd_exe.write_text("stub", encoding="utf-8")

    handler = _make_handler(
        tmp_path,
        defaults={
            "steamcmd_root": str(steamcmd_dir),
            "gameservers_root": str(tmp_path / "GameServers"),
        },
    )
    _write_instance_config(tmp_path, "10", {"map": "theisland_wp"})

    monkeypatch.setattr(subprocess, "Popen", _FakeSteamCmdTimeoutProc)

    resp = handler.handle("install_server", {"instance_id": "10"})

    assert resp["status"] == "error"
    assert resp["data"]["ok"] is False
    assert any("timed out" in e.lower() for e in resp["data"]["errors"])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only provisioning scope")
def test_install_server_can_target_hidden_master_layout(tmp_path, monkeypatch):
    steamcmd_dir = tmp_path / "steamcmd"
    steamcmd_exe = steamcmd_dir / "steamcmd.exe"
    steamcmd_dir.mkdir(parents=True, exist_ok=True)
    steamcmd_exe.write_text("stub", encoding="utf-8")

    gameservers_root = tmp_path / "GameServers"
    handler = _make_handler(
        tmp_path,
        defaults={
            "steamcmd_root": str(steamcmd_dir),
            "gameservers_root": str(gameservers_root),
        },
    )

    monkeypatch.setattr(subprocess, "Popen", _FakeSteamCmdProc)

    resp = handler.handle("install_server", {"install_target": "master"})

    expected_root = gameservers_root / ".ncc" / "masters" / "ark" / "ArkSA"
    expected_exe = expected_root / "ShooterGame" / "Binaries" / "Win64" / "ArkAscendedServer.exe"

    assert resp["status"] == "success"
    assert resp["data"]["ok"] is True
    assert resp["data"]["install_target"] == "master"
    assert resp["data"]["install_root"] == str(expected_root)
    assert expected_exe.is_file()
