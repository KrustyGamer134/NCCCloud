import json
from pathlib import Path

from core.plugin_handler import PluginHandler


def test_cloud_registered_plugin_handler_uses_registry_key_and_embedded_install_root(tmp_path):
    plugin_json = json.loads((Path(__file__).resolve().parents[1] / "plugins" / "ark" / "plugin.json").read_text(encoding="utf-8"))
    plugin_json["install_root"] = "arkSA"

    cluster_root = tmp_path
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
                "gameservers_root": str(cluster_root / "ArkRoot"),
                "steamcmd_root": str(cluster_root / "steamcmd"),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    instance_cfg = (
        cluster_root
        / "instances"
        / "ark_survival_ascended"
        / "10"
        / "config"
        / "instance_config.json"
    )
    instance_cfg.parent.mkdir(parents=True, exist_ok=True)
    instance_cfg.write_text(
        json.dumps({"schema_version": 1, "map": "theisland_wp", "mods": [], "passive_mods": [], "ports": []}),
        encoding="utf-8",
    )

    handler = PluginHandler(plugin_json, "", str(cluster_root), plugin_key="ark_survival_ascended")

    layout = handler._resolve_layout("10")

    assert layout is not None
    assert layout["install_root"] == str(cluster_root / "ArkRoot" / "arkSA" / "theisland_wp_1")
