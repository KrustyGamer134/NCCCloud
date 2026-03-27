import socket
import shutil
from pathlib import Path


from core.admin_api import AdminAPI


def _reserve_free_port_tcp() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        return int(s.getsockname()[1])
    finally:
        s.close()


def _reserve_free_port_udp() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


def _copy_ark_plugin_into(tmp_root: Path) -> None:
    repo_root = Path.cwd()
    src = repo_root / "plugins" / "ark"
    if not src.exists():
        raise RuntimeError(f"Missing source plugin folder: {src}")

    dest = tmp_root / "plugins" / "ark"
    if dest.exists():
        shutil.rmtree(dest)

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("instances", "__pycache__"))


def _read_text_if_exists(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def test_user_workflow_smoke_in_process(tmp_path):
    cluster_root = Path(tmp_path)

    _copy_ark_plugin_into(cluster_root)

    defaults_path = cluster_root / "plugins" / "ark" / "plugin_defaults.json"
    if defaults_path.exists():
        defaults_path.unlink()

    api = None
    try:
        api = AdminAPI.build_default(plugin_dir=str(cluster_root / "plugins"), state_file=None, cluster_root=str(cluster_root))

        v = api.validate_environment(str(cluster_root))
        assert isinstance(v, dict)
        assert v.get("ok") is True

        add = api.add_instance("ark", "99")
        assert add.get("status") == "success"

        blocked_instance_cfg = cluster_root / "plugins" / "ark" / "instances" / "99" / "config" / "instance_config.json"
        assert not blocked_instance_cfg.exists()
        assert not defaults_path.exists()

        # blocked port check (no writes)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        blocked_port = int(s.getsockname()[1])

        try:
            before_defaults = _read_text_if_exists(defaults_path)
            before_inst = _read_text_if_exists(blocked_instance_cfg)

            res_block = api.configure_instance(
                "ark",
                "99",
                "TheIsland_WP",
                game_port=_reserve_free_port_udp(),
                rcon_port=blocked_port,  # blocked
                mods=["123", "456"],
                passive_mods=["999"],
                map_mod="777",
            )
            assert res_block.get("status") == "error"
            assert "Port availability check failed" in (res_block.get("message") or "")

            assert _read_text_if_exists(defaults_path) == before_defaults
            assert _read_text_if_exists(blocked_instance_cfg) == before_inst
            assert not defaults_path.exists()
            assert not blocked_instance_cfg.exists()

        finally:
            s.close()

        add2 = api.add_instance("ark", "10")
        assert add2.get("status") == "success"

        cfg = api.configure_instance(
            "ark",
            "10",
            "TheIsland_WP",
            game_port=_reserve_free_port_udp(),
            rcon_port=_reserve_free_port_tcp(),
            mods=["123", "456", "456"],  # duplicate in a single list should error
            passive_mods=["999"],
            map_mod="777",
        )
        assert cfg.get("status") == "error"
        assert "duplicate" in (cfg.get("message") or "").lower()

        cfg = api.configure_instance(
            "ark",
            "10",
            "TheIsland_WP",
            game_port=_reserve_free_port_udp(),
            rcon_port=_reserve_free_port_tcp(),
            mods=["123", "456"],
            passive_mods=["999", "999"],  # duplicate should error
            map_mod="777",
        )
        assert cfg.get("status") == "error"
        assert "duplicate" in (cfg.get("message") or "").lower()

        cfg = api.configure_instance(
            "ark",
            "10",
            "TheIsland_WP",
            game_port=_reserve_free_port_udp(),
            rcon_port=_reserve_free_port_tcp(),
            mods=["123", "456"],
            passive_mods=["999"],
            map_mod="777",
        )
        assert cfg.get("status") == "success"

        instance_cfg_path = cluster_root / "plugins" / "ark" / "instances" / "10" / "config" / "instance_config.json"
        assert instance_cfg_path.exists()

        show = api.show_config("ark", "10")
        assert show.get("status") == "success"
        data = show.get("data") or {}
        eff = data.get("effective") or {}

        active = eff.get("active_mods") or []
        passive = eff.get("passive_mods") or []

        assert len(active) >= 1
        assert active[0] == "777"
        assert active == ["777", "123", "456"]
        assert passive == ["999"]

    finally:
        if api is not None:
            api.close()
