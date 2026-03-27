############################################################
# SECTION: CG-L7-2 Scheduled Restart Semantics Enforcement
# Purpose:
# Verify scheduled restart semantics:
#   - restart_reason="scheduled" is honored
#   - crash_stability_count resets to 0
#   - crash_total_count does NOT change
#   - DISABLED blocks scheduled restarts
# Lifecycle Ownership:
# Test Layer
# Phase:
# Layer 7-2
# Constraints:
# - No time-of-day logic
# - No scheduler feature expansion
# - No threshold logic changes
# - No persistence changes
# - Determinism preserved
############################################################

from core.plugin_registry import PluginRegistry
from core.state_manager import StateManager
from core.orchestrator import Orchestrator
from tests.helpers_install import ensure_ready


def build_orchestrator(cluster_root="."):
    registry = PluginRegistry(plugin_dir="plugins")
    state = StateManager(state_file=None)
    orchestrator = Orchestrator(registry, state, cluster_root=cluster_root)
    registry.load_all()
    return registry, state, orchestrator


def test_scheduled_restart_resets_stability_only_and_preserves_total():
    registry, state, orchestrator = build_orchestrator(cluster_root=".")

    plugin = "ark"
    instance = "TestMap"

    # Put instance in RUNNING (so restart is legal regardless)
    ensure_ready(orchestrator, plugin, instance)
    orchestrator.start_instance(plugin, instance)
    assert state.get_state(plugin, instance) == "RUNNING"

    # Seed counters (no policy logic triggered)
    key = orchestrator._ensure_counter_entry(plugin, instance)
    orchestrator._crash_counters[key]["crash_total_count"] = 5
    orchestrator._crash_counters[key]["crash_stability_count"] = 3

    # Scheduled restart
    resp = orchestrator.restart_instance(plugin, instance, restart_reason="scheduled")
    assert resp.get("status") == "success"
    assert state.get_state(plugin, instance) == "RUNNING"

    # Semantics:
    # - stability resets
    # - total unchanged
    assert orchestrator.get_crash_stability_count(plugin, instance) == 0
    assert orchestrator.get_crash_total_count(plugin, instance) == 5

    orchestrator.shutdown_plugin(plugin)


def test_scheduled_restart_is_blocked_when_disabled():
    registry, state, orchestrator = build_orchestrator(cluster_root=".")

    plugin = "ark"
    instance = "TestMap"

    ensure_ready(orchestrator, plugin, instance)
    orchestrator.start_instance(plugin, instance)
    assert state.get_state(plugin, instance) == "RUNNING"

    # Seed counters
    key = orchestrator._ensure_counter_entry(plugin, instance)
    orchestrator._crash_counters[key]["crash_total_count"] = 2
    orchestrator._crash_counters[key]["crash_stability_count"] = 2

    # Disable (Layer 5 authority)
    orchestrator.disable_instance(plugin, instance, reason="test")
    assert state.get_state(plugin, instance) == "DISABLED"

    # Scheduled restart must be refused
    resp = orchestrator.restart_instance(plugin, instance, restart_reason="scheduled")
    assert resp.get("status") != "success"
    assert state.get_state(plugin, instance) == "DISABLED"

    # Counters must remain unchanged on refused restart
    assert orchestrator.get_crash_total_count(plugin, instance) == 2
    assert orchestrator.get_crash_stability_count(plugin, instance) == 2

    orchestrator.shutdown_plugin(plugin)


def test_scheduled_restart_does_not_require_running_state():
    """
    Your implementation allows scheduled restarts even if the instance isn't RUNNING
    (it only blocks non-scheduled restarts in non-RUNNING state).
    This test locks that behavior in place without changing it.
    """
    registry, state, orchestrator = build_orchestrator(cluster_root=".")

    plugin = "ark"
    instance = "TestMap"

    # Ensure exists but is STOPPED
    state.set_state(plugin, instance, "STOPPED")
    assert state.get_state(plugin, instance) == "STOPPED"

    # Seed counters
    key = orchestrator._ensure_counter_entry(plugin, instance)
    orchestrator._crash_counters[key]["crash_total_count"] = 1
    orchestrator._crash_counters[key]["crash_stability_count"] = 9

    # Scheduled restart should proceed and end RUNNING
    resp = orchestrator.restart_instance(plugin, instance, restart_reason="scheduled")
    assert resp.get("status") == "success"
    assert state.get_state(plugin, instance) == "RUNNING"

    # Stability resets; total unchanged
    assert orchestrator.get_crash_stability_count(plugin, instance) == 0
    assert orchestrator.get_crash_total_count(plugin, instance) == 1

    orchestrator.shutdown_plugin(plugin)