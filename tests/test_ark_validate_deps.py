import json
from pathlib import Path

from core.plugin_handler import PluginHandler


def _make_handler(tmp_path, cluster_root=None, defaults=None):
    real_ark = Path(__file__).resolve().parents[1] / "plugins" / "ark"
    with open(real_ark / "plugin.json", encoding="utf-8") as f:
        plugin_json = json.load(f)
    plugin_dir = tmp_path / "plugins" / "ark"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    if defaults is not None:
        (plugin_dir / "plugin_config.json").write_text(
            json.dumps({"schema_version": 1, **defaults}), encoding="utf-8"
        )
    return PluginHandler(
        plugin_json=plugin_json,
        plugin_dir=str(plugin_dir),
        cluster_root=str(cluster_root or tmp_path),
    )


def _write_instance_config(tmp_path, instance_id, config):
    path = (
        tmp_path
        / "plugins"
        / "ark"
        / "instances"
        / instance_id
        / "config"
        / "plugin_instance_config.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config), encoding="utf-8")


def test_validate_all_required_fields_present_returns_ok(tmp_path):
    handler = _make_handler(tmp_path)
    _write_instance_config(
        tmp_path,
        "10",
        {"map": "theisland_wp", "game_port": 7777, "rcon_port": 27020, "admin_password": "pw"},
    )
    resp = handler.handle("validate", {"instance_id": "10"})
    assert resp["status"] == "success"
    assert resp["data"]["ok"] is True
    assert resp["data"]["errors"] == []


def test_validate_missing_required_fields_returns_errors(tmp_path):
    handler = _make_handler(tmp_path)
    _write_instance_config(tmp_path, "10", {})
    resp = handler.handle("validate", {"instance_id": "10"})
    assert resp["status"] == "error"
    data = resp["data"]
    assert data["ok"] is False
    assert any("map" in e for e in data["errors"])
    assert any("game_port" in e for e in data["errors"])
    assert any("rcon_port" in e for e in data["errors"])
    assert any("admin_password" in e for e in data["errors"])


def test_validate_admin_password_in_defaults_satisfies_requirement(tmp_path):
    handler = _make_handler(tmp_path, defaults={"admin_password": "securepassword"})
    _write_instance_config(
        tmp_path,
        "10",
        {"map": "theisland_wp", "game_port": 7777, "rcon_port": 27020},
    )
    resp = handler.handle("validate", {"instance_id": "10"})
    assert resp["status"] == "success"
    assert resp["data"]["ok"] is True
    assert not any("admin_password" in e for e in resp["data"]["errors"])


def test_validate_warns_when_steamcmd_not_configured(tmp_path):
    # No steamcmd_root in defaults → steamcmd_dir is None → warns
    handler = _make_handler(tmp_path)
    _write_instance_config(
        tmp_path,
        "10",
        {"map": "theisland_wp", "game_port": 7777, "rcon_port": 27020, "admin_password": "pw"},
    )
    resp = handler.handle("validate", {"instance_id": "10"})
    assert any("SteamCMD" in w for w in resp["data"]["warnings"])


def test_validate_warns_when_server_exe_missing_after_install_dir_exists(tmp_path):
    gameservers_root = tmp_path / "GameServers"
    install_dir = gameservers_root / "ArkSA" / "theisland_wp_1"
    install_dir.mkdir(parents=True, exist_ok=True)
    # Exe is NOT created — validate should warn, not error
    handler = _make_handler(tmp_path, defaults={"gameservers_root": str(gameservers_root)})
    _write_instance_config(
        tmp_path,
        "10",
        {"map": "theisland_wp", "game_port": 7777, "rcon_port": 27020, "admin_password": "pw"},
    )
    resp = handler.handle("validate", {"instance_id": "10"})
    assert resp["status"] == "success"
    assert resp["data"]["ok"] is True
    assert any("executable" in w.lower() or "not found" in w.lower() for w in resp["data"]["warnings"])


def test_validate_response_has_ok_errors_warnings_keys(tmp_path):
    handler = _make_handler(tmp_path)
    _write_instance_config(tmp_path, "10", {})
    resp = handler.handle("validate", {"instance_id": "10"})
    assert {"ok", "errors", "warnings"} <= set(resp["data"].keys())
    assert isinstance(resp["data"]["ok"], bool)
    assert isinstance(resp["data"]["errors"], list)
    assert isinstance(resp["data"]["warnings"], list)


def test_validate_legacy_install_root_resolves_ok(tmp_path):
    legacy_root = tmp_path / "legacy_install"
    legacy_root.mkdir(parents=True, exist_ok=True)
    handler = _make_handler(tmp_path)
    _write_instance_config(
        tmp_path,
        "10",
        {
            "install_root": str(legacy_root),
            "map": "theisland_wp",
            "game_port": 7777,
            "rcon_port": 27020,
            "admin_password": "pw",
        },
    )
    resp = handler.handle("validate", {"instance_id": "10"})
    assert resp["status"] == "success"
    assert resp["data"]["ok"] is True


def test_validate_partial_required_fields_errors_report_each_missing(tmp_path):
    handler = _make_handler(tmp_path)
    # Provide only map — other fields missing
    _write_instance_config(tmp_path, "10", {"map": "theisland_wp"})
    resp = handler.handle("validate", {"instance_id": "10"})
    assert resp["data"]["ok"] is False
    errors = resp["data"]["errors"]
    # map is present, so no error for it
    assert not any("map" in e and "map_" not in e for e in errors)
    assert any("game_port" in e for e in errors)
    assert any("rcon_port" in e for e in errors)
    assert any("admin_password" in e for e in errors)
