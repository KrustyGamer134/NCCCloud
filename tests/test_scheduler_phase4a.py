############################################################
# SECTION: CG-L7-1 Scheduler Routing Integrity Test
# Purpose:
# Ensure SchedulerEngine never calls plugin transport directly.
# Lifecycle Ownership:
# Test Layer
# Phase:
# Layer 7-1
# Constraints:
# - No time-of-day logic
# - No scheduler feature changes
# - Determinism preserved
############################################################

from core.scheduler_engine import SchedulerEngine


class _OrchestratorStub:
    """
    Minimal orchestrator surface required by SchedulerEngine for Phase 4A.

    This avoids coupling the test to Orchestrator methods that may not exist yet,
    while still enforcing the key CG-L7-1 rule: scheduler must not call plugin
    transport methods like send_action().
    """

    def __init__(self):
        self.calls = []

    # If scheduler ever tries to call plugin directly, fail immediately.
    def send_action(self, *args, **kwargs):
        raise AssertionError("Scheduler attempted direct plugin call via send_action")

    def reset_stability_for_plugin(self, plugin_name):
        self.calls.append(("reset_stability_for_plugin", plugin_name))

    def clear_disabled_for_plugin(self, plugin_name):
        self.calls.append(("clear_disabled_for_plugin", plugin_name))

    def notify_plugin_window_open(self, plugin_name):
        self.calls.append(("notify_plugin_window_open", plugin_name))

    def notify_plugin_window_close(self, plugin_name):
        self.calls.append(("notify_plugin_window_close", plugin_name))


def test_scheduler_never_calls_plugin_transport_directly():
    """
    CG-L7-1 Gate:
    SchedulerEngine must never call plugin transport directly (e.g., send_action).
    It may only signal intent through orchestrator-level methods.
    """

    orch = _OrchestratorStub()
    sched = SchedulerEngine(orch)

    started = sched.begin_maintenance_cycle(["ark"], current_time=0)
    assert started is True

    # A tick should not require any direct plugin calls either.
    sched.tick(current_time=1)

    # If scheduler called send_action, the test would have failed already.
    # Also confirm scheduler did use orchestrator facade calls (Phase 4A behavior).
    assert ("reset_stability_for_plugin", "ark") in orch.calls
    assert ("clear_disabled_for_plugin", "ark") in orch.calls
    assert ("notify_plugin_window_open", "ark") in orch.calls