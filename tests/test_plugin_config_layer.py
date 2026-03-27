import json
import socket
import shutil
from pathlib import Path

import pytest

from core.plugin_config import (
    PluginConfigError,
    ensure_plugin_defaults_file,
    instance_config_path,
    legacy_instance_config_path,
    legacy_plugin_defaults_path,
    load_plugin_defaults,
    load_instance_config,
    plugin_defaults_path,
    compute_effective_mods,
    write_instance_config_atomic,
    write_plugin_defaults_atomic,
)
from core.port_check import check_ports_availability


def _copy_ark_plugin_into(tmp_root: Path) -> None:
    repo_root = Path.cwd()
    src = repo_root / "plugins" / "ark"
    if not src.exists():
        raise RuntimeError(f"Missing source plugin folder: {src}")

    dest = tmp_root / "plugins" / "ark"
    if dest.exists():
        shutil.rmtree(dest)

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)

    # IMPORTANT FOR THESE TESTS:
    # We assert "no files were written" during configure when ports are blocked.
    # The real repo may already contain plugin defaults + instance configs.
    # Remove them from the copied temp plugin so the assertions mean what they say.

    cfg = dest / "plugin_config.json"
    try:
        cfg.unlink(missing_ok=True)
    except TypeError:
        if cfg.exists():
            cfg.unlink()

    inst_dir = dest / "instances"
    if inst_dir.exists():
        shutil.rmtree(inst_dir)


def test_load_plugin_defaults_falls_back_when_missing(tmp_path):
    defaults = load_plugin_defaults(str(tmp_path), "ark")
    assert defaults["schema_version"] == 1
    assert defaults["mods"] == []
    assert defaults["passive_mods"] == []
    assert "missing_file:" in str(defaults.get("_load_error") or "")



def test_write_plugin_defaults_atomic_persists_validated_defaults(tmp_path):
    path = write_plugin_defaults_atomic(
        str(tmp_path),
        "ark",
        {
            "schema_version": 1,
            "mods": ["100"],
            "passive_mods": ["200"],
            "test_mode": False,
            "steamcmd_path": r"C:\SteamCMD\steamcmd.exe",
            "default_game_port_start": 30000,
            "default_rcon_port_start": 31000,
        },
    )

    assert path.is_file()
    defaults = load_plugin_defaults(str(tmp_path), "ark")
    assert defaults["mods"] == ["100"]
    assert defaults["passive_mods"] == ["200"]
    assert defaults["test_mode"] is False
    assert defaults["steamcmd_path"] == r"C:\SteamCMD\steamcmd.exe"
    assert defaults["default_game_port_start"] == 30000
    assert defaults["default_rcon_port_start"] == 31000
    assert path == plugin_defaults_path(str(tmp_path), "ark")


def test_load_plugin_defaults_reads_legacy_plugin_config_name(tmp_path):
    path = legacy_plugin_defaults_path(str(tmp_path), "ark")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "mods": ["100"], "passive_mods": ["200"]}),
        encoding="utf-8",
    )

    defaults = load_plugin_defaults(str(tmp_path), "ark")

    assert defaults["mods"] == ["100"]
    assert defaults["passive_mods"] == ["200"]

def test_defaults_file_created_if_missing(tmp_path):
    cluster_root = str(tmp_path)
    (tmp_path / "plugins" / "ark").mkdir(parents=True, exist_ok=True)

    path, created = ensure_plugin_defaults_file(cluster_root, "ark")
    assert created is True
    assert path.exists()

    defaults = load_plugin_defaults(cluster_root, "ark")
    assert defaults["schema_version"] == 1
    assert defaults["mods"] == []
    assert defaults["passive_mods"] == []
    assert path == plugin_defaults_path(cluster_root, "ark")


def test_write_instance_config_atomic_uses_canonical_name_and_load_reads_legacy_name(tmp_path):
    legacy_path = legacy_instance_config_path(str(tmp_path), "ark", "10")
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "map": "TheIsland_WP",
                "mods": [],
                "passive_mods": [],
                "ports": [],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_instance_config(str(tmp_path), "ark", "10")
    assert loaded["map"] == "TheIsland_WP"

    path = write_instance_config_atomic(
        str(tmp_path),
        "ark",
        "11",
        map_name="TheIsland_WP",
        map_mod=None,
        mods=[],
        passive_mods=[],
        ports=[],
    )
    assert path == instance_config_path(str(tmp_path), "ark", "11")


def test_duplicate_detection_within_lists_raises():
    with pytest.raises(PluginConfigError):
        compute_effective_mods(
            plugin_defaults_mods=["1", "1"],
            plugin_defaults_passive_mods=[],
            instance_mods=[],
            instance_passive_mods=[],
            map_mod=None,
        )

    with pytest.raises(PluginConfigError):
        compute_effective_mods(
            plugin_defaults_mods=[],
            plugin_defaults_passive_mods=["9", "9"],
            instance_mods=[],
            instance_passive_mods=[],
            map_mod=None,
        )

    with pytest.raises(PluginConfigError):
        compute_effective_mods(
            plugin_defaults_mods=[],
            plugin_defaults_passive_mods=[],
            instance_mods=["2", "2"],
            instance_passive_mods=[],
            map_mod=None,
        )

    with pytest.raises(PluginConfigError):
        compute_effective_mods(
            plugin_defaults_mods=[],
            plugin_defaults_passive_mods=[],
            instance_mods=[],
            instance_passive_mods=["3", "3"],
            map_mod=None,
        )


def test_map_mod_rules():
    with pytest.raises(PluginConfigError):
        compute_effective_mods(
            plugin_defaults_mods=["777"],
            plugin_defaults_passive_mods=[],
            instance_mods=[],
            instance_passive_mods=[],
            map_mod="777",
        )

    with pytest.raises(PluginConfigError):
        compute_effective_mods(
            plugin_defaults_mods=[],
            plugin_defaults_passive_mods=[],
            instance_mods=["777"],
            instance_passive_mods=[],
            map_mod="777",
        )

    with pytest.raises(PluginConfigError):
        compute_effective_mods(
            plugin_defaults_mods=[],
            plugin_defaults_passive_mods=["777"],
            instance_mods=[],
            instance_passive_mods=[],
            map_mod="777",
        )

    with pytest.raises(PluginConfigError):
        compute_effective_mods(
            plugin_defaults_mods=[],
            plugin_defaults_passive_mods=[],
            instance_mods=[],
            instance_passive_mods=["777"],
            map_mod="777",
        )


def test_stable_merge_order_map_mod_first_and_dedupe():
    out = compute_effective_mods(
        plugin_defaults_mods=["123", "456"],
        plugin_defaults_passive_mods=["p1"],
        instance_mods=["456", "789"],
        instance_passive_mods=["p1", "p2"],
        map_mod="777",
    )
    assert out["active_mods"] == ["777", "123", "456", "789"]
    assert out["passive_mods"] == ["p1", "p2"]


def test_overlap_active_and_passive_errors():
    with pytest.raises(PluginConfigError):
        compute_effective_mods(
            plugin_defaults_mods=["1"],
            plugin_defaults_passive_mods=["2"],
            instance_mods=["3"],
            instance_passive_mods=["1"],  # overlap
            map_mod=None,
        )


def test_core_port_check_blocked_when_already_bound():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        res = check_ports_availability([{"name": "rcon", "port": port, "proto": "tcp"}])
        assert res["ok"] is False
        assert len(res["blocked"]) == 1
        assert res["blocked"][0]["port"] == port
    finally:
        s.close()


def test_configure_writes_nothing_if_ports_blocked(tmp_path):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]

    try:
        from core.plugin_registry import PluginRegistry
        from core.state_manager import StateManager
        from core.orchestrator import Orchestrator

        _copy_ark_plugin_into(tmp_path)

        reg = PluginRegistry(plugin_dir=str(tmp_path / "plugins"))
        reg.load_all()

        state = StateManager(state_file=None)
        orch = Orchestrator(reg, state, cluster_root=str(tmp_path))

        res = orch.configure_instance_config(
            plugin_name="ark",
            instance_id="10",
            map_name="TheIsland_WP",
            game_port=7777,
            rcon_port=port,  # blocked
            mods=["123"],
            passive_mods=[],
            map_mod=None,
        )
        assert res["status"] == "error"
        assert "Port availability check failed" in res.get("message", "")

        assert not (tmp_path / "plugins" / "ark" / "plugin_config.json").exists()
        assert not (tmp_path / "plugins" / "ark" / "instances" / "10" / "config" / "plugin_instance_config.json").exists()

    finally:
        s.close()
        try:
            if "reg" in locals():
                for _name, rec in list(getattr(reg, "_plugins", {}).items()):
                    proc = rec.get("process")
                    try:
                        if proc is not None and proc.is_alive():
                            proc.terminate()
                            proc.join(timeout=1)
                    except Exception:
                        pass
        except Exception:
            pass


def test_plugin_registry_loads_optional_capabilities_metadata(tmp_path):
    from core.plugin_registry import PluginRegistry

    plugin_dir = tmp_path / "plugins" / "demo"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"schema_version": 1, "name": "demo",
                    "game_id": "demo_game", "display_name": "Demo"}),
        encoding="utf-8",
    )
    (plugin_dir / "capabilities.json").write_text(
        json.dumps({"schema_version": 1, "install_server_app_id": "123"}),
        encoding="utf-8",
    )

    reg = PluginRegistry(plugin_dir=str(tmp_path / "plugins"))
    reg.load_all()
    record = reg.get("demo")
    assert record is not None
    assert record["metadata"]["capabilities"]["install_server_app_id"] == "123"


def test_plugin_registry_load_all_does_not_run_validate_on_load(tmp_path, monkeypatch):
    from core.plugin_registry import PluginRegistry
    import core.plugin_handler as ph

    handle_calls = []
    original_handle = ph.PluginHandler.handle

    def _tracking_handle(self, action, payload):
        handle_calls.append(action)
        return original_handle(self, action, payload)

    monkeypatch.setattr(ph.PluginHandler, "handle", _tracking_handle)

    plugin_dir = tmp_path / "plugins" / "demo"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(
        json.dumps({"schema_version": 1, "name": "demo",
                    "game_id": "demo_game", "display_name": "Demo"}),
        encoding="utf-8",
    )

    reg = PluginRegistry(plugin_dir=str(tmp_path / "plugins"))
    reg.load_all()

    assert reg.get("demo") is not None
    assert handle_calls == []


def test_plugin_registry_skips_none_metadata_safely(tmp_path):
    from core.plugin_registry import PluginRegistry

    plugin_dir = tmp_path / "plugins" / "broken"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text("null\n", encoding="utf-8")

    reg = PluginRegistry(plugin_dir=str(tmp_path / "plugins"))
    reg.load_all()

    assert reg.list_all() == []


def test_adminapi_build_default_treats_invalid_first_run_plugin_metadata_as_no_plugins(tmp_path):
    from core.admin_api import AdminAPI

    plugin_dir = tmp_path / "plugins"
    broken = plugin_dir / "broken"
    broken.mkdir(parents=True, exist_ok=True)
    (broken / "plugin.json").write_text("[]\n", encoding="utf-8")

    api = AdminAPI.build_default(plugin_dir=str(plugin_dir), state_file=None, cluster_root=str(tmp_path))
    try:
        assert api.get_all_plugins() == []
    finally:
        api.close()



