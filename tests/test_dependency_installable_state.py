from __future__ import annotations

import json
from pathlib import Path

from core.orchestrator import Orchestrator
from core.state_manager import StateManager


class _Registry:
    def list_all(self):
        return ["ark"]

    def get_metadata(self, plugin_name):
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

    def get(self, plugin_name):
        return None


def _write_cluster_config(root: Path, steamcmd_root: str, *, gameservers_root: str = ""):
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "cluster_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "install_root_dir": str(root / "instances"),
                "backup_dir": str(root / "backups"),
                "cluster_name": "arkSA",
                "base_game_port": 30000,
                "base_rcon_port": 31000,
                "shared_mods": [],
                "shared_passive_mods": [],
                "instances": [],
                "gameservers_root": gameservers_root,
                "steamcmd_root": steamcmd_root,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def test_dependency_report_marks_steamcmd_install_available(tmp_path: Path):
    steamcmd_root = tmp_path / "steamcmd"
    steamcmd_root.mkdir()
    _write_cluster_config(tmp_path, str(steamcmd_root))

    orch = Orchestrator(_Registry(), StateManager(state_file=None), cluster_root=str(tmp_path))
    report = orch.get_plugin_dependency_report("ark")

    result = report["plugins"]["ark"]["results"][0]
    assert result["status"] == "install_available"
    assert report["plugins"]["ark"]["status"] == "install_available"


def test_dependency_report_marks_steamcmd_install_failed(tmp_path: Path):
    steamcmd_root = tmp_path / "steamcmd"
    steamcmd_root.mkdir()
    _write_cluster_config(tmp_path, str(steamcmd_root))

    orch = Orchestrator(_Registry(), StateManager(state_file=None), cluster_root=str(tmp_path))
    orch._set_app_dependency_failed("steamcmd", "SteamCMD install failed: boom")
    report = orch.get_plugin_dependency_report("ark")

    result = report["plugins"]["ark"]["results"][0]
    assert result["status"] == "install_failed"
    assert "boom" in result["details"]
    assert report["plugins"]["ark"]["status"] == "install_failed"
    assert (tmp_path / "state" / "app_dependency_state.json").is_file()
    assert not (tmp_path / "config" / "app_dependency_state.json").exists()


def test_dependency_report_marks_steamcmd_installed(tmp_path: Path):
    steamcmd_root = tmp_path / "steamcmd"
    steamcmd_root.mkdir()
    (steamcmd_root / "steamcmd.exe").write_text("stub", encoding="utf-8")
    _write_cluster_config(tmp_path, str(steamcmd_root))

    orch = Orchestrator(_Registry(), StateManager(state_file=None), cluster_root=str(tmp_path))
    report = orch.get_plugin_dependency_report("ark")

    result = report["plugins"]["ark"]["results"][0]
    assert result["status"] == "installed"
    assert result["details"].endswith("steamcmd.exe")
    assert report["plugins"]["ark"]["status"] == "installed"


def test_dependency_report_resolves_relative_steamcmd_root_against_cluster_root(tmp_path: Path):
    steamcmd_root = tmp_path / "relative-steamcmd"
    steamcmd_root.mkdir()
    _write_cluster_config(tmp_path, "relative-steamcmd")

    orch = Orchestrator(_Registry(), StateManager(state_file=None), cluster_root=str(tmp_path))
    report = orch.get_plugin_dependency_report("ark")

    result = report["plugins"]["ark"]["results"][0]
    assert result["status"] == "install_available"
    assert result["details"] == str(steamcmd_root)


def test_app_setup_report_uses_same_effective_relative_steamcmd_root(tmp_path: Path):
    steamcmd_root = tmp_path / "relative-steamcmd"
    steamcmd_root.mkdir()
    _write_cluster_config(tmp_path, "relative-steamcmd")

    orch = Orchestrator(_Registry(), StateManager(state_file=None), cluster_root=str(tmp_path))
    report = orch.get_app_setup_report()

    steamcmd_root_result = [item for item in report["results"] if item["id"] == "steamcmd_root"][0]
    steamcmd_result = [item for item in report["results"] if item["id"] == "steamcmd"][0]
    assert steamcmd_root_result["details"] == str(steamcmd_root)
    assert steamcmd_result["details"] == str(steamcmd_root)


def test_app_setup_report_marks_startup_installed_when_roots_configured_and_exe_exists(tmp_path: Path):
    steamcmd_root = tmp_path / "steamcmd"
    steamcmd_root.mkdir()
    steamcmd_exe = steamcmd_root / "steamcmd.exe"
    steamcmd_exe.write_text("stub", encoding="utf-8")
    gameservers_root = tmp_path / "gameservers"
    gameservers_root.mkdir()
    _write_cluster_config(tmp_path, str(steamcmd_root), gameservers_root=str(gameservers_root))

    orch = Orchestrator(_Registry(), StateManager(state_file=None), cluster_root=str(tmp_path))
    report = orch.get_app_setup_report()

    assert report["status"] == "installed"
    gameservers_result = [item for item in report["results"] if item["id"] == "gameservers_root"][0]
    steamcmd_root_result = [item for item in report["results"] if item["id"] == "steamcmd_root"][0]
    steamcmd_result = [item for item in report["results"] if item["id"] == "steamcmd"][0]
    assert gameservers_result["status"] == "installed"
    assert gameservers_result["details"] == str(gameservers_root)
    assert steamcmd_root_result["status"] == "installed"
    assert steamcmd_root_result["details"] == str(steamcmd_root)
    assert steamcmd_result["status"] == "installed"
    assert steamcmd_result["details"] == str(steamcmd_exe)


def test_app_setup_report_treats_existing_steamcmd_exe_as_installed_without_probe(tmp_path: Path, monkeypatch):
    steamcmd_root = tmp_path / "steamcmd"
    steamcmd_root.mkdir()
    steamcmd_exe = steamcmd_root / "steamcmd.exe"
    steamcmd_exe.write_text("stub", encoding="utf-8")
    gameservers_root = tmp_path / "gameservers"
    gameservers_root.mkdir()
    _write_cluster_config(tmp_path, str(steamcmd_root), gameservers_root=str(gameservers_root))

    orch = Orchestrator(_Registry(), StateManager(state_file=None), cluster_root=str(tmp_path))
    monkeypatch.setattr(
        "core.steamcmd.probe_steamcmd_executable",
        lambda path, **_kwargs: (_ for _ in ()).throw(AssertionError(f"unexpected probe: {path}")),
    )

    first = orch.get_app_setup_report()
    second = orch.get_app_setup_report()
    first_steamcmd = [item for item in first["results"] if item["id"] == "steamcmd"][0]
    second_steamcmd = [item for item in second["results"] if item["id"] == "steamcmd"][0]

    assert first["status"] == "installed"
    assert first_steamcmd["status"] == "installed"
    assert second_steamcmd["status"] == "installed"

    orch._mark_app_setup_report_dirty()
    third = orch.get_app_setup_report()
    third_steamcmd = [item for item in third["results"] if item["id"] == "steamcmd"][0]

    assert third["status"] == "installed"
    assert third_steamcmd["status"] == "installed"

    refreshed = orch.refresh_app_setup_report()
    refreshed_steamcmd = [item for item in refreshed["results"] if item["id"] == "steamcmd"][0]

    assert refreshed["status"] == "installed"
    assert refreshed_steamcmd["status"] == "installed"

def test_app_setup_report_ignores_probe_failure_when_steamcmd_exe_exists(tmp_path: Path, monkeypatch):
    steamcmd_root = tmp_path / "steamcmd"
    steamcmd_root.mkdir()
    steamcmd_exe = steamcmd_root / "steamcmd.exe"
    steamcmd_exe.write_text("stub", encoding="utf-8")
    gameservers_root = tmp_path / "gameservers"
    gameservers_root.mkdir()
    _write_cluster_config(tmp_path, str(steamcmd_root), gameservers_root=str(gameservers_root))

    orch = Orchestrator(_Registry(), StateManager(state_file=None), cluster_root=str(tmp_path))

    monkeypatch.setattr(
        "core.steamcmd.probe_steamcmd_executable",
        lambda path, **_kwargs: (False, f"SteamCMD bootstrap failed: {path}"),
    )

    report = orch.get_app_setup_report()

    steamcmd_result = [item for item in report["results"] if item["id"] == "steamcmd"][0]
    assert report["status"] == "installed"
    assert steamcmd_result["status"] == "installed"
    assert steamcmd_result["details"] == str(steamcmd_exe)
