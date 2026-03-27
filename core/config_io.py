import json
import os
import tempfile
from pathlib import Path
from .config_models import ClusterConfig, InstanceConfig


def load_cluster_config(path):
    path = Path(path)

    data = json.loads(path.read_text())

    instances = [
        InstanceConfig(**inst)
        for inst in data.get("instances", [])
    ]

    cluster = ClusterConfig(
        install_root_dir=data["install_root_dir"],
        cluster_name=data.get("cluster_name", "arkSA"),
        cluster_id=data.get("cluster_id"),
        base_game_port=data["base_game_port"],
        base_rcon_port=data["base_rcon_port"],
        backup_dir=data["backup_dir"],
        graceful_shutdown_seconds=data.get("graceful_shutdown_seconds", 45),
        auto_update=data.get("auto_update", False),
        shared_mods=data.get("shared_mods", []),
        shared_passive_mods=data.get("shared_passive_mods", []),
        instances=instances,
        schema_version=data.get("schema_version", 1),
        gameservers_root=data.get("gameservers_root", ""),
        steamcmd_root=data.get("steamcmd_root", ""),
    )

    return cluster.normalized()


def save_cluster_config(cluster_config, path):
    path = Path(path)

    data = {
        "schema_version": cluster_config.schema_version,
        "install_root_dir": cluster_config.install_root_dir,
        "cluster_name": cluster_config.cluster_name,
        "cluster_id": cluster_config.cluster_id,
        "base_game_port": cluster_config.base_game_port,
        "base_rcon_port": cluster_config.base_rcon_port,
        "backup_dir": cluster_config.backup_dir,
        "graceful_shutdown_seconds": cluster_config.graceful_shutdown_seconds,
        "auto_update": cluster_config.auto_update,
        "shared_mods": cluster_config.shared_mods,
        "shared_passive_mods": cluster_config.shared_passive_mods,
        "gameservers_root": cluster_config.gameservers_root,
        "steamcmd_root": cluster_config.steamcmd_root,
        "instances": [
            inst.__dict__ for inst in cluster_config.instances
        ],
    }

    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
