from dataclasses import dataclass, field, replace
from typing import List, Optional
import uuid


class ConfigValidationError(Exception):
    pass


PORT_MIN = 1024
PORT_MAX = 65535
CONFIG_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class InstanceConfig:
    plugin: str
    instance_id: str
    map_name: str

    display_name: Optional[str] = None
    install_path: Optional[str] = None
    game_port: Optional[int] = None
    rcon_port: Optional[int] = None

    required_mod: Optional[str] = None
    mods: List[str] = field(default_factory=list)
    passive_mods: List[str] = field(default_factory=list)

    def normalized(self, cluster_root: str, base_game_port: int, base_rcon_port: int, index: int):
        if not self.map_name or not self.map_name.strip():
            raise ConfigValidationError("map_name is required")

        display_name = self.display_name or self.map_name

        install_path = self.install_path or f"{cluster_root}/{self.instance_id}"

        game_port = self.game_port if self.game_port is not None else base_game_port + index
        rcon_port = self.rcon_port if self.rcon_port is not None else base_rcon_port + index

        return replace(
            self,
            display_name=display_name,
            install_path=install_path,
            game_port=game_port,
            rcon_port=rcon_port,
        )


@dataclass(frozen=True)
class ClusterConfig:
    install_root_dir: str
    cluster_name: str
    cluster_id: Optional[str]

    base_game_port: int
    base_rcon_port: int
    backup_dir: str

    graceful_shutdown_seconds: int = 45
    auto_update: bool = False

    shared_mods: List[str] = field(default_factory=list)
    shared_passive_mods: List[str] = field(default_factory=list)

    instances: List[InstanceConfig] = field(default_factory=list)

    schema_version: int = CONFIG_SCHEMA_VERSION
    gameservers_root: str = ""
    steamcmd_root: str = ""

    def normalized(self):
        if not self.install_root_dir or not self.install_root_dir.strip():
            raise ConfigValidationError("install_root_dir required")
        install_root_dir = self.install_root_dir.strip()

        cluster_name = (self.cluster_name or "").strip()
        if not cluster_name:
            cluster_name = "arkSA"

        gameservers_root = (self.gameservers_root or "").strip()
        steamcmd_root = (self.steamcmd_root or "").strip()

        if not (PORT_MIN <= self.base_game_port <= PORT_MAX):
            raise ConfigValidationError("base_game_port out of range")

        if not (PORT_MIN <= self.base_rcon_port <= PORT_MAX):
            raise ConfigValidationError("base_rcon_port out of range")

        cluster_id = self.cluster_id or str(uuid.uuid4())

        normalized_instances = []
        used_game_ports = set()
        used_rcon_ports = set()
        used_ids = set()

        for index, inst in enumerate(self.instances):
            if inst.instance_id in used_ids:
                raise ConfigValidationError("duplicate instance_id")

            used_ids.add(inst.instance_id)

            norm = inst.normalized(
                install_root_dir,
                self.base_game_port,
                self.base_rcon_port,
                index,
            )

            if norm.game_port in used_game_ports:
                raise ConfigValidationError("game_port collision")

            if norm.rcon_port in used_rcon_ports:
                raise ConfigValidationError("rcon_port collision")

            used_game_ports.add(norm.game_port)
            used_rcon_ports.add(norm.rcon_port)

            normalized_instances.append(norm)

        return replace(
            self,
            install_root_dir=install_root_dir,
            cluster_name=cluster_name,
            gameservers_root=gameservers_root,
            steamcmd_root=steamcmd_root,
            cluster_id=cluster_id,
            instances=normalized_instances,
        )

    def with_updated_instance(self, updated_instance: InstanceConfig):
        for inst in self.instances:
            if inst.instance_id == updated_instance.instance_id:
                if inst.map_name != updated_instance.map_name:
                    raise ConfigValidationError("map_name is immutable")

        new_instances = [
            updated_instance if i.instance_id == updated_instance.instance_id else i
            for i in self.instances
        ]

        return replace(self, instances=new_instances)
