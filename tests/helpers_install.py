from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from core.instance_layout import ensure_instance_layout


def _seed_ark_test_instance(cluster_root: str, instance_id: str) -> None:
    """
    Keep lifecycle tests deterministic by providing Ark instance values that
    avoid machine-specific defaults and real binary launches.
    """
    root = Path(cluster_root)
    inst_cfg = root / "plugins" / "ark" / "instances" / str(instance_id) / "config" / "instance_config.json"
    inst_cfg.parent.mkdir(parents=True, exist_ok=True)

    cfg = {}
    if inst_cfg.exists():
        try:
            cfg = json.loads(inst_cfg.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}

    cfg.setdefault("schema_version", 1)
    cfg.setdefault("map", "TheIsland_WP")
    cfg.setdefault("game_port", 7777)
    cfg.setdefault("rcon_port", 27020)
    cfg["test_mode"] = False
    cfg["gameservers_root"] = str(root / ".pytest_gameservers")
    cfg.setdefault("cluster_name", "pytest_cluster")
    cfg["install_root"] = str(Path(cfg["gameservers_root"]) / "ArkSA" / f"{cfg['map']}_1")
    # admin_password is required by required_launch_fields; set per-instance so plugin
    # defaults remain empty and perform_graceful_stop skips RCON in tests.
    cfg.setdefault("admin_password", "pytest_admin")

    inst_cfg.write_text(json.dumps(cfg, indent=2, sort_keys=True), encoding="utf-8")

    # Ensure deterministic executable path exists for non-simulated starts.
    install_root = Path(str(cfg["install_root"]))
    server_exe = (
        install_root
        / "ShooterGame"
        / "Binaries"
        / "Win64"
        / "ArkAscendedServer.exe"
    )
    server_exe.parent.mkdir(parents=True, exist_ok=True)

    source_exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "hostname.exe"
    if not source_exe.exists():
        source_exe = Path(sys.executable)

    if not server_exe.exists():
        shutil.copyfile(source_exe, server_exe)


def _seed_e2e_harness_test_instance(cluster_root: str, instance_id: str) -> None:
    root = Path(cluster_root)
    inst_cfg = root / "plugins" / "e2e_harness" / "instances" / str(instance_id) / "config" / "instance_config.json"
    inst_cfg.parent.mkdir(parents=True, exist_ok=True)

    rcon_port = 29000 + int(str(instance_id))
    gameservers_root = root / ".pytest_gameservers"
    install_root = gameservers_root / "E2EHarness" / f"instance_{instance_id}"

    cfg = {
        "schema_version": 1,
        "map": "HarnessMap",
        "game_port": 27015,
        "rcon_port": rcon_port,
        "admin_password": "e2e",
        "rcon_enabled": True,
        "gameservers_root": str(gameservers_root),
        "cluster_name": "pytest_cluster",
        "install_root": str(install_root),
    }
    inst_cfg.write_text(json.dumps(cfg, indent=2, sort_keys=True), encoding="utf-8")


    server_exe = install_root / "fake_server.py"
    server_exe.parent.mkdir(parents=True, exist_ok=True)
    source_exe = root / "plugins" / "e2e_harness" / "fake_server.py"
    shutil.copyfile(source_exe, server_exe)


def ensure_ready(orchestrator, plugin_name: str, instance_id: str) -> None:
    """
    Make an instance startable under CG-PROVISION-2:
    - scaffold instance layout
    - run explicit install (STOPPED-only)
    """
    cluster_root = getattr(orchestrator, "_cluster_root", None) or "."
    ensure_instance_layout(str(cluster_root), plugin_name, instance_id)

    if str(plugin_name) == "ark":
        _seed_ark_test_instance(str(cluster_root), str(instance_id))
    if str(plugin_name) == "e2e_harness":
        _seed_e2e_harness_test_instance(str(cluster_root), str(instance_id))

    r = orchestrator.install_instance(plugin_name, instance_id)
    if r.get("status") != "success":
        raise AssertionError(f"install_instance failed for {plugin_name}/{instance_id}: {r}")




