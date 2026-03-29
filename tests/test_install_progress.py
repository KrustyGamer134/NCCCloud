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


def test_get_install_progress_prefers_metadata_source_log_from_offset(tmp_path):
    plugin_name = "ark"
    instance_id = "11"
    install_root = tmp_path / "GameServers" / "ArkSA" / "TheIsland_WP"
    logs_dir = install_root / "logs"
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
                "install_root": str(install_root),
                "mods": [],
                "passive_mods": [],
            }
        ),
        encoding="utf-8",
    )

    native_log_path = tmp_path / "steamcmd_console.log"
    prefix = "old prefix line\nanother old line\n"
    progress_lines = (
        "Update state (0x61) downloading, progress: 62.35 (1 / 2)\n"
        "Update state (0x81) verifying update, progress: 7.21 (1 / 2)\n"
    )
    native_log_path.write_text(prefix + progress_lines, encoding="utf-8")

    (logs_dir / "steamcmd_install.log").write_text("", encoding="utf-8")
    (logs_dir / "steamcmd_progress_source.json").write_text(
        json.dumps(
            {
                "source": "steamcmd_native_console_log",
                "log_path": str(native_log_path),
                "start_offset": len(prefix.encode("utf-8")),
            }
        ),
        encoding="utf-8",
    )

    api = AdminAPI(_StubOrchestrator(tmp_path))
    response = api.get_install_progress(plugin_name, instance_id, last_lines=50)

    assert response["status"] == "success"
    assert response["data"]["state"] == "validating"
    assert response["data"]["steamcmd_progress"]["phase"] == "validating"
    assert response["data"]["steamcmd_progress"]["percent"] == 7.21
    assert response["data"]["steamcmd_log_tail"] == [
        "Update state (0x61) downloading, progress: 62.35 (1 / 2)",
        "Update state (0x81) verifying update, progress: 7.21 (1 / 2)",
    ]
    assert response["data"]["paths"]["steamcmd_progress_source_log"] == str(native_log_path)


def test_get_install_progress_recovers_source_metadata_from_install_log_header(tmp_path):
    plugin_name = "ark"
    instance_id = "12"
    install_root = tmp_path / "GameServers" / "ArkSA" / "TheIsland_WP"
    logs_dir = install_root / "logs"
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
                "install_root": str(install_root),
                "mods": [],
                "passive_mods": [],
            }
        ),
        encoding="utf-8",
    )

    native_log_path = tmp_path / "steamcmd_console_recovered.log"
    prefix = "old line\n"
    progress_lines = (
        "Update state (0x61) downloading, progress: 62.35 (1 / 2)\n"
        "Update state (0x81) verifying update, progress: 7.21 (1 / 2)\n"
    )
    native_log_path.write_text(prefix + progress_lines, encoding="utf-8")

    (logs_dir / "install_server.log").write_text(
        "\n".join(
            [
                "steam_install - app_id=2430930 - SteamCMD (networked)",
                f"instance_id={instance_id}",
                f"steamcmd_native_log={native_log_path}",
                f"steamcmd_native_log_offset={len(prefix.encode('utf-8'))}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (logs_dir / "steamcmd_install.log").write_text("", encoding="utf-8")
    (logs_dir / "steamcmd_progress_source.json").write_text("{}", encoding="utf-8")

    api = AdminAPI(_StubOrchestrator(tmp_path))
    response = api.get_install_progress(plugin_name, instance_id, last_lines=50)

    assert response["status"] == "success"
    assert response["data"]["progress_metadata"]["log_path"] == str(native_log_path)
    assert response["data"]["progress_metadata"]["start_offset"] == len(prefix.encode("utf-8"))
    assert response["data"]["steamcmd_progress"]["phase"] == "validating"
    assert response["data"]["steamcmd_progress"]["percent"] == 7.21


def test_get_install_progress_falls_back_to_master_logs_while_installing(tmp_path):
    plugin_name = "ark"
    instance_id = "13"
    gameservers_root = tmp_path / "GameServers"
    instance_logs_dir = gameservers_root / "ArkSA" / "TheIsland_WP" / "logs"
    instance_logs_dir.mkdir(parents=True, exist_ok=True)
    master_logs_dir = gameservers_root / ".ncc" / "masters" / plugin_name / "ArkSA" / "logs"
    master_logs_dir.mkdir(parents=True, exist_ok=True)

    plugin_defaults = tmp_path / "plugins" / plugin_name
    plugin_defaults.mkdir(parents=True, exist_ok=True)
    (plugin_defaults / "plugin_defaults.json").write_text(
        json.dumps({"schema_version": 1, "mods": [], "passive_mods": [], "gameservers_root": str(gameservers_root)}),
        encoding="utf-8",
    )

    instance_config_dir = tmp_path / "plugins" / plugin_name / "instances" / instance_id / "config"
    instance_config_dir.mkdir(parents=True, exist_ok=True)
    (instance_config_dir / "instance_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "map": "TheIsland_WP",
                "install_root": str(gameservers_root / "ArkSA" / "TheIsland_WP"),
                "mods": [],
                "passive_mods": [],
            }
        ),
        encoding="utf-8",
    )

    native_log_path = tmp_path / "steamcmd_console_master.log"
    native_log_path.write_text(
        "Update state (0x61) downloading, progress: 62.35 (1 / 2)\n",
        encoding="utf-8",
    )
    (master_logs_dir / "install_server.log").write_text(
        "\n".join(
            [
                "steam_install - app_id=2430930 - SteamCMD (networked)",
                f"instance_id={instance_id}",
                f"steamcmd_native_log={native_log_path}",
                "steamcmd_native_log_offset=0",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (master_logs_dir / "steamcmd_progress_source.json").write_text(
        json.dumps({"log_path": str(native_log_path), "source": "steamcmd_native_console_log", "start_offset": 0}),
        encoding="utf-8",
    )

    api = AdminAPI(_StubOrchestrator(tmp_path))
    api._registry = type("_Registry", (), {"get_metadata": lambda self, _plugin_name: {"install_subfolder": "ArkSA"}})()
    api.get_cluster_config_fields = lambda fields=None: {"status": "success", "data": {"fields": {"gameservers_root": str(gameservers_root)}}}
    api._orchestrator.get_instance_install_status = lambda _plugin_name, _instance_id: "INSTALLING"
    response = api.get_install_progress(plugin_name, instance_id, last_lines=50)

    assert response["status"] == "success"
    assert response["data"]["paths"]["logs_dir"] == str(master_logs_dir)
    assert response["data"]["steamcmd_progress"]["phase"] == "downloading"


def test_get_log_tail_falls_back_to_master_logs_while_installing(tmp_path):
    plugin_name = "ark"
    instance_id = "14"
    gameservers_root = tmp_path / "GameServers"
    instance_logs_dir = gameservers_root / "ArkSA" / "TheIsland_WP" / "logs"
    instance_logs_dir.mkdir(parents=True, exist_ok=True)
    master_logs_dir = gameservers_root / ".ncc" / "masters" / plugin_name / "ArkSA" / "logs"
    master_logs_dir.mkdir(parents=True, exist_ok=True)

    plugin_defaults = tmp_path / "plugins" / plugin_name
    plugin_defaults.mkdir(parents=True, exist_ok=True)
    (plugin_defaults / "plugin_defaults.json").write_text(
        json.dumps({"schema_version": 1, "mods": [], "passive_mods": [], "gameservers_root": str(gameservers_root)}),
        encoding="utf-8",
    )

    instance_config_dir = tmp_path / "plugins" / plugin_name / "instances" / instance_id / "config"
    instance_config_dir.mkdir(parents=True, exist_ok=True)
    (instance_config_dir / "instance_config.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "map": "TheIsland_WP",
                "install_root": str(gameservers_root / "ArkSA" / "TheIsland_WP"),
                "mods": [],
                "passive_mods": [],
            }
        ),
        encoding="utf-8",
    )

    (master_logs_dir / "steamcmd_install.log").write_text("master install line\n", encoding="utf-8")

    api = AdminAPI(_StubOrchestrator(tmp_path))
    api._registry = type("_Registry", (), {"get_metadata": lambda self, _plugin_name: {"install_subfolder": "ArkSA"}})()
    api.get_cluster_config_fields = lambda fields=None: {"status": "success", "data": {"fields": {"gameservers_root": str(gameservers_root)}}}
    api._orchestrator.get_instance_install_status = lambda _plugin_name, _instance_id: "INSTALLING"
    response = api.get_log_tail(plugin_name, instance_id, "steamcmd_install", last_lines=50)

    assert response["status"] == "success"
    assert response["data"]["found"] is True
    assert response["data"]["path"] == str(master_logs_dir / "steamcmd_install.log")
    assert response["data"]["lines"] == ["master install line"]
