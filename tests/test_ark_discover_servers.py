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


def test_discover_servers_scans_relative_install_root_under_gameservers_root(tmp_path):
    gameservers_root = tmp_path / "Ark"
    install_root = gameservers_root / "BriansPlayground"
    server_root = install_root / "brianstheisland_wp"
    exe_path = server_root / "ShooterGame" / "Binaries" / "Win64" / "ArkAscendedServer.exe"
    exe_path.parent.mkdir(parents=True, exist_ok=True)
    exe_path.write_text("", encoding="utf-8")

    handler = _make_handler(
        tmp_path,
        defaults={"gameservers_root": str(gameservers_root), "install_root": "BriansPlayground"},
    )

    resp = handler.handle("discover_servers", {})

    assert resp["status"] == "success"
    assert resp["data"]["ok"] is True
    assert resp["data"]["candidates"] == [
        {
            "install_path": str(server_root),
            "detected_map": "TheIsland_WP",
            "executable_path": str(exe_path),
            "ports": [
                {"name": "game", "proto": "udp"},
                {"name": "rcon", "proto": "tcp"},
            ],
            "ini_fields": {},
            "managed_match": False,
            "managed_instance_id": "",
        }
    ]


def test_discover_servers_marks_existing_managed_install_root(tmp_path):
    gameservers_root = tmp_path / "Ark"
    install_root = gameservers_root / "BriansPlayground"
    server_root = install_root / "brianstheisland_wp"
    exe_path = server_root / "ShooterGame" / "Binaries" / "Win64" / "ArkAscendedServer.exe"
    exe_path.parent.mkdir(parents=True, exist_ok=True)
    exe_path.write_text("", encoding="utf-8")

    handler = _make_handler(
        tmp_path,
        defaults={"gameservers_root": str(gameservers_root), "install_root": "BriansPlayground"},
    )
    _write_instance_config(tmp_path, "10", {"install_root": str(server_root)})

    resp = handler.handle("discover_servers", {})

    assert resp["status"] == "success"
    assert resp["data"]["candidates"][0]["managed_match"] is True
    assert resp["data"]["candidates"][0]["managed_instance_id"] == "10"


def test_discover_servers_detects_ports_from_plugin_ini_file(tmp_path):
    gameservers_root = tmp_path / "Ark"
    install_root = gameservers_root / "BriansPlayground"
    server_root = install_root / "brianstheisland_wp"
    exe_path = server_root / "ShooterGame" / "Binaries" / "Win64" / "ArkAscendedServer.exe"
    exe_path.parent.mkdir(parents=True, exist_ok=True)
    exe_path.write_text("", encoding="utf-8")
    ini_path = server_root / "ShooterGame" / "Saved" / "Config" / "WindowsServer" / "GameUserSettings.ini"
    ini_path.parent.mkdir(parents=True, exist_ok=True)
    ini_path.write_text(
        "[SessionSettings]\nPort=7777\n\n[ServerSettings]\nRCONPort=27020\n",
        encoding="utf-8",
    )

    handler = _make_handler(
        tmp_path,
        defaults={"gameservers_root": str(gameservers_root), "install_root": "BriansPlayground"},
    )

    resp = handler.handle("discover_servers", {})

    assert resp["status"] == "success"
    assert resp["data"]["candidates"][0]["ports"] == [
        {"name": "game", "port": 7777, "proto": "udp"},
        {"name": "rcon", "port": 27020, "proto": "tcp"},
    ]
    assert resp["data"]["candidates"][0]["ini_fields"] == {
        "game_port": 7777,
        "rcon_port": 27020,
    }


def test_discover_servers_preserves_ini_backed_fields(tmp_path):
    gameservers_root = tmp_path / "Ark"
    install_root = gameservers_root / "BriansPlayground"
    server_root = install_root / "brianragnarok_wp"
    exe_path = server_root / "ShooterGame" / "Binaries" / "Win64" / "ArkAscendedServer.exe"
    exe_path.parent.mkdir(parents=True, exist_ok=True)
    exe_path.write_text("", encoding="utf-8")
    ini_path = server_root / "ShooterGame" / "Saved" / "Config" / "WindowsServer" / "GameUserSettings.ini"
    ini_path.parent.mkdir(parents=True, exist_ok=True)
    ini_path.write_text(
        "[SessionSettings]\n"
        "Port=7781\n"
        "SessionName=Brianragnarok\n\n"
        "[ServerSettings]\n"
        "RCONPort=27022\n"
        "RCONEnabled=True\n"
        "ServerAdminPassword=supersecret\n",
        encoding="utf-8",
    )

    handler = _make_handler(
        tmp_path,
        defaults={"gameservers_root": str(gameservers_root), "install_root": "BriansPlayground"},
    )

    resp = handler.handle("discover_servers", {})

    assert resp["status"] == "success"
    assert resp["data"]["candidates"][0]["ini_fields"] == {
        "game_port": 7781,
        "rcon_port": 27022,
        "rcon_enabled": True,
        "admin_password": "supersecret",
        "server_name": "Brianragnarok",
    }


def test_discover_servers_reads_mods_passive_mods_and_player_count_from_ini(tmp_path):
    gameservers_root = tmp_path / "Ark"
    install_root = gameservers_root / "BriansPlayground"
    server_root = install_root / "brianragnarok_wp"
    exe_path = server_root / "ShooterGame" / "Binaries" / "Win64" / "ArkAscendedServer.exe"
    exe_path.parent.mkdir(parents=True, exist_ok=True)
    exe_path.write_text("", encoding="utf-8")
    ini_path = server_root / "ShooterGame" / "Saved" / "Config" / "WindowsServer" / "GameUserSettings.ini"
    ini_path.parent.mkdir(parents=True, exist_ok=True)
    ini_path.write_text(
        "[ServerSettings]\n"
        "ActiveMods=111,222\n"
        "passivemods=333,444\n\n"
        "[/Script/Engine.GameSession]\n"
        "MaxPlayers=20\n",
        encoding="utf-8",
    )

    handler = _make_handler(
        tmp_path,
        defaults={"gameservers_root": str(gameservers_root), "install_root": "BriansPlayground"},
    )

    resp = handler.handle("discover_servers", {})

    assert resp["status"] == "success"
    assert resp["data"]["candidates"][0]["ini_fields"]["mods"] == ["111", "222"]
    assert resp["data"]["candidates"][0]["ini_fields"]["passive_mods"] == ["333", "444"]
    assert resp["data"]["candidates"][0]["ini_fields"]["max_players"] == 20


def test_discover_servers_prefers_game_created_savedarks_map_folder_over_install_folder_name(tmp_path):
    gameservers_root = tmp_path / "Ark"
    install_root = gameservers_root / "BriansPlayground"
    server_root = install_root / "brianragnarok_wp"
    exe_path = server_root / "ShooterGame" / "Binaries" / "Win64" / "ArkAscendedServer.exe"
    exe_path.parent.mkdir(parents=True, exist_ok=True)
    exe_path.write_text("", encoding="utf-8")
    savedarks_map_dir = server_root / "ShooterGame" / "Saved" / "SavedArks" / "Ragnarok"
    savedarks_map_dir.mkdir(parents=True, exist_ok=True)

    handler = _make_handler(
        tmp_path,
        defaults={"gameservers_root": str(gameservers_root), "install_root": "BriansPlayground"},
    )

    resp = handler.handle("discover_servers", {})

    assert resp["status"] == "success"
    assert resp["data"]["candidates"][0]["detected_map"] == "Ragnarok_WP"


def test_discover_servers_skips_hidden_master_install_root(tmp_path):
    gameservers_root = tmp_path / "Ark"
    master_root = gameservers_root / ".ncc" / "masters" / "ark" / "ArkSA"
    exe_path = master_root / "ShooterGame" / "Binaries" / "Win64" / "ArkAscendedServer.exe"
    exe_path.parent.mkdir(parents=True, exist_ok=True)
    exe_path.write_text("", encoding="utf-8")

    handler = _make_handler(
        tmp_path,
        defaults={"gameservers_root": str(gameservers_root)},
    )

    resp = handler.handle("discover_servers", {})

    assert resp["status"] == "success"
    assert resp["data"]["ok"] is True
    assert resp["data"]["candidates"] == []
