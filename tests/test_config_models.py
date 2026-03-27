import pytest
from core.config_models import (
    ClusterConfig,
    InstanceConfig,
    ConfigValidationError,
)


def valid_cluster():
    return ClusterConfig(
        install_root_dir="root",
        cluster_name="cluster",
        cluster_id=None,
        base_game_port=30000,
        base_rcon_port=31000,
        backup_dir="backup",
        instances=[
            InstanceConfig(
                plugin="ark",
                instance_id="island",
                map_name="TheIsland",
            )
        ],
    )


def test_valid_config_passes():
    cluster = valid_cluster().normalized()
    assert cluster.cluster_id is not None
    assert cluster.instances[0].display_name == "TheIsland"
    assert cluster.gameservers_root == ""


def test_blank_cluster_name_normalizes_to_default():
    cluster = ClusterConfig(
        install_root_dir="root",
        cluster_name="   ",
        cluster_id=None,
        base_game_port=30000,
        base_rcon_port=31000,
        backup_dir="backup",
        instances=[],
    ).normalized()

    assert cluster.cluster_name == "arkSA"


def test_missing_map_name_fails():
    cluster = ClusterConfig(
        install_root_dir="root",
        cluster_name="cluster",
        cluster_id=None,
        base_game_port=30000,
        base_rcon_port=31000,
        backup_dir="backup",
        instances=[
            InstanceConfig(
                plugin="ark",
                instance_id="island",
                map_name="",
            )
        ],
    )

    with pytest.raises(ConfigValidationError):
        cluster.normalized()


def test_port_collision_fails():
    cluster = ClusterConfig(
        install_root_dir="root",
        cluster_name="cluster",
        cluster_id=None,
        base_game_port=30000,
        base_rcon_port=31000,
        backup_dir="backup",
        instances=[
            InstanceConfig(
                plugin="ark",
                instance_id="a",
                map_name="MapA",
                game_port=30001,
            ),
            InstanceConfig(
                plugin="ark",
                instance_id="b",
                map_name="MapB",
                game_port=30001,
            ),
        ],
    )

    with pytest.raises(ConfigValidationError):
        cluster.normalized()


def test_map_name_immutable():
    cluster = valid_cluster().normalized()

    updated = InstanceConfig(
        plugin="ark",
        instance_id="island",
        map_name="DifferentMap",
    )

    with pytest.raises(ConfigValidationError):
        cluster.with_updated_instance(updated)
