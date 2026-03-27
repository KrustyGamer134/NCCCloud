import socket
from pathlib import Path

from core.plugin_config import resolve_instance_config_path
from tests.helpers_install import ensure_ready


def _can_connect(host: str, port: int, timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def test_e2e_harness_full_workflow(built_orchestrator, tmp_path):
    """
    Deterministic end-to-end harness test:
      validate -> add layout/install (core stub) -> install_deps -> start -> rcon_exec -> stop

    Constraints:
      - no downloads
      - no sleeps / threads
      - deterministic file markers
    """
    _registry, _state, orch = built_orchestrator

    plugin = "e2e_harness"
    instance_id = "1"

    # Ensure the plugin exists in the repo for this test run
    repo_root = Path(__file__).resolve().parents[1]
    plugin_dir = repo_root / "plugins" / plugin
    assert plugin_dir.exists(), f"Missing plugin folder: {plugin_dir}"

    # Ensure core install stub + layout (STOPPED-only)
    ensure_ready(orch, plugin, instance_id)

    # Plugin stub installs (no network)
    r = orch.send_action(plugin, "install_deps", {"instance_id": instance_id})
    assert r.get("status") == "success"

    # Start harness server (subprocess); should block until READY
    r = orch.start_instance(plugin, instance_id)
    assert r.get("status") == "success", r

    host = "127.0.0.1"
    port = 0
    config_path = resolve_instance_config_path(".", plugin, instance_id)
    if config_path.exists():
        import json

        config = json.loads(config_path.read_text(encoding="utf-8"))
        port = int(config.get("rcon_port") or 0)
    assert port > 0

    # RCON call must succeed
    r = orch.send_action(plugin, "rcon_exec", {"instance_id": instance_id, "command": "SaveWorld"})
    assert r.get("status") == "success"

    # Stop uses orchestrator STOP flow -> graceful_stop
    r = orch.stop_instance(plugin, instance_id)
    assert r.get("status") == "success"

    assert _can_connect(host, port) is False
