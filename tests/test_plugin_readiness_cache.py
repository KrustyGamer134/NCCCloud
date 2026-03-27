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

    def load_all(self):
        return None


def _write_cluster_config(root: Path, steamcmd_root: str = ""):
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
                "gameservers_root": "",
                "steamcmd_root": str(steamcmd_root),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_plugin_readiness_report_reuses_cache_until_dirty(tmp_path: Path, monkeypatch):
    _write_cluster_config(tmp_path)
    orch = Orchestrator(_Registry(), StateManager(state_file=None), cluster_root=str(tmp_path))
    load_calls = []

    def _load_plugin_defaults(cluster_root, plugin_name):
        load_calls.append((cluster_root, plugin_name))
        return {"test_mode": True}

    monkeypatch.setattr("core.plugin_config.load_plugin_defaults", _load_plugin_defaults)

    first = orch.get_plugin_readiness_report("ark")
    second = orch.get_plugin_readiness_report("ark")

    assert first["status"] == "missing"
    assert second == first
    assert len(load_calls) == 2

    orch._mark_plugin_readiness_dirty("ark")
    third = orch.get_plugin_readiness_report("ark")

    assert third["status"] == "missing"
    assert len(load_calls) == 2

    refreshed = orch.refresh_plugin_readiness_report("ark")

    assert refreshed["status"] == "missing"
    assert len(load_calls) == 4


def test_plugin_readiness_report_marks_installable_dependency(tmp_path: Path, monkeypatch):
    steamcmd_root = tmp_path / "steamcmd"
    steamcmd_root.mkdir()
    _write_cluster_config(tmp_path, str(steamcmd_root))
    orch = Orchestrator(_Registry(), StateManager(state_file=None), cluster_root=str(tmp_path))

    monkeypatch.setattr("core.plugin_config.load_plugin_defaults", lambda cluster_root, plugin_name: {"test_mode": False})

    report = orch.get_plugin_readiness_report("ark")

    assert report["status"] == "install_available"
    assert any(str(item.get("label")) == "SteamCMD" for item in report["results"])


def test_plugin_readiness_report_requires_install_root_and_admin_password(tmp_path: Path, monkeypatch):
    _write_cluster_config(tmp_path)
    orch = Orchestrator(_Registry(), StateManager(state_file=None), cluster_root=str(tmp_path))

    monkeypatch.setattr(
        "core.plugin_config.load_plugin_defaults",
        lambda cluster_root, plugin_name: {"test_mode": False, "install_root": "", "admin_password": ""},
    )

    report = orch.get_plugin_readiness_report("ark")

    assert report["status"] == "missing"
    labels = {str(item.get("label")) for item in report["results"]}
    assert "Install Root" in labels
    assert "Admin Password" in labels
