import pytest

from core.plugin_registry import PluginRegistry
from core.state_manager import StateManager
from core.orchestrator import Orchestrator


@pytest.fixture
def built_orchestrator():
    registry = PluginRegistry(plugin_dir="plugins", cluster_root=".")
    state = StateManager(state_file=None)

    # IMPORTANT (CG-PROVISION-2):
    # install_instance / ensure_ready require cluster_root to be configured.
    orchestrator = Orchestrator(registry, state, cluster_root=".")

    registry.load_all()

    try:
        yield registry, state, orchestrator
    finally:
        # Best-effort cleanup of any plugin processes started by load_all()
        for plugin_name in registry.list_all():
            try:
                orchestrator.shutdown_plugin(plugin_name)
            except Exception:
                pass