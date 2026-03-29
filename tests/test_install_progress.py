import json
from pathlib import Path

from core.admin_api import AdminAPI


class _StubOrchestrator:
    def __init__(self, cluster_root: Path):
        self._cluster_root = str(cluster_root)


def test_get_install_progress_parses_download_and_validate_percent(tmp_path):
    plugin_name = "ark"
    instance_id = "10"
    logs_dir = tmp_path / "GameServers" / "ArkSA" / "TheIsland_WP" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    plugin_defaults = tmp_path / "plugins" / plugin_name
    plugin_defaults.mkdir(parents=True, exist_ok=True)
    (plugin_defaults / "plugin_defaults.json").write_text(
        json.dumps({"schema_version": 1, "mods": [], "passive_mods": []}),
        encoding="utf-8",
    )

    instance_config_dir = tmp_path / "plugins" / plugin_name / "instances" / instance_id / "config"
    instance_config_dir.mkdir(parents=True, exist_ok=True)
    (instance_config_dir / "instance_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "map": "TheIsland_WP",
                "install_root": str(tmp_path / "GameServers" / "ArkSA" / "TheIsland_WP"),
                "mods": [],
                "passive_mods": [],
            }
        ),
        encoding="utf-8",
    )

    (logs_dir / "steamcmd_install.log").write_text(
        "\n".join(
            [
                " Update state (0x61) downloading, progress: 99.90 (13084913286 / 13098544774)",
                " Update state (0x81) verifying update, progress: 14.69 (1924301314 / 13098544774)",
                "Success! App '2430930' fully installed.",
            ]
        ),
        encoding="utf-8",
    )
    (logs_dir / "steamcmd_progress_source.json").write_text(
        json.dumps({"source": "steamcmd_native_console_log"}),
        encoding="utf-8",
    )

    api = AdminAPI(_StubOrchestrator(tmp_path))
    response = api.get_install_progress(plugin_name, instance_id, last_lines=50)

    assert response["status"] == "success"
    assert response["data"]["state"] == "completed"
    assert response["data"]["steamcmd_progress"]["phase"] == "validating"
    assert response["data"]["steamcmd_progress"]["percent"] == 14.69
    assert response["data"]["steamcmd_progress"]["completed"] is True
