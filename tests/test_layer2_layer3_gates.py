from tests.helpers_install import ensure_ready


# ------------------------------------------------------------
# Layer 2 â€” Lifecycle Legality
# ------------------------------------------------------------

def test_layer2_lifecycle_legality(built_orchestrator):
    registry, state, orchestrator = built_orchestrator

    plugin = "ark"
    instance = "TestMap"

    # Start allowed
    ensure_ready(orchestrator, plugin, instance)
    orchestrator.start_instance(plugin, instance)
    assert state.get_state(plugin, instance) == "RUNNING"

    orchestrator._runtime_running = lambda plugin_name, instance_id: state.get_state(plugin_name, instance_id) == state.RUNNING

    # Restart allowed while running
    result = orchestrator.restart_instance(plugin, instance, restart_reason="manual")
    assert result["status"] == "success"

    # Stop allowed
    orchestrator.stop_instance(plugin, instance)
    assert state.get_state(plugin, instance) != "RUNNING"

    # Restart while stopped should fail (illegal transition)
    result = orchestrator.restart_instance(plugin, instance, restart_reason="manual")
    assert result["status"] != "success"


# ------------------------------------------------------------
# Layer 3 â€” Crash Restart When Running
# ------------------------------------------------------------

def test_layer3_crash_restart_when_running(built_orchestrator):
    registry, state, orchestrator = built_orchestrator

    plugin = "ark"
    instance = "TestMap"

    ensure_ready(orchestrator, plugin, instance)
    orchestrator.start_instance(plugin, instance)
    assert state.get_state(plugin, instance) == "RUNNING"
    orchestrator._runtime_running = lambda plugin_name, instance_id: state.get_state(plugin_name, instance_id) == state.RUNNING

    # Inject crash event deterministically
    orchestrator._handle_event(
        plugin,
        {
            "event_type": "instance_crashed",
            "data": {"instance_id": instance},
        },
    )

    # After crash while running -> should restart (still RUNNING)
    assert state.get_state(plugin, instance) == "RUNNING"

    # Crash counter should increment
    total = orchestrator.get_crash_total_count(plugin, instance)
    assert total >= 1


# ------------------------------------------------------------
# Layer 3 â€” Ignore Crash When Not Running
# ------------------------------------------------------------

def test_layer3_ignore_when_not_running(built_orchestrator):
    registry, state, orchestrator = built_orchestrator

    plugin = "ark"
    instance = "TestMap"

    # Ensure instance not running
    assert state.get_state(plugin, instance) != "RUNNING"

    # Inject crash event
    orchestrator._handle_event(
        plugin,
        {
            "event_type": "instance_crashed",
            "data": {"instance_id": instance},
        },
    )

    # State should remain unchanged (no restart)
    assert state.get_state(plugin, instance) != "RUNNING"

    # Crash counters should remain zero
    total = orchestrator.get_crash_total_count(plugin, instance)
    assert total == 0


# ------------------------------------------------------------
# Layer 4 â€” Crash Counter (Instrumentation Only)
# ------------------------------------------------------------

def test_layer4_crash_event_increments_crash_count(built_orchestrator):
    registry, state, orchestrator = built_orchestrator

    plugin = "ark"
    instance = "TestMap"

    ensure_ready(orchestrator, plugin, instance)
    orchestrator.start_instance(plugin, instance)
    assert orchestrator.get_crash_total_count(plugin, instance) == 0

    orchestrator._handle_event(
        plugin,
        {
            "event_type": "instance_crashed",
            "data": {"instance_id": instance},
        },
    )

    assert orchestrator.get_crash_total_count(plugin, instance) == 1


def test_layer4_manual_restart_does_not_increment_crash_count(built_orchestrator):
    registry, state, orchestrator = built_orchestrator

    plugin = "ark"
    instance = "TestMap"

    ensure_ready(orchestrator, plugin, instance)
    orchestrator.start_instance(plugin, instance)

    orchestrator._runtime_running = lambda plugin_name, instance_id: state.get_state(plugin_name, instance_id) == state.RUNNING

    # Manual restart
    result = orchestrator.restart_instance(plugin, instance, restart_reason="manual")
    assert result["status"] == "success"

    # Crash counter should remain unchanged
    assert orchestrator.get_crash_total_count(plugin, instance) == 0


def test_layer4_threshold_resolution_precedence_instance_over_plugin_over_global(built_orchestrator):
    registry, state, orchestrator = built_orchestrator

    plugin = "ark"
    instance = "TestMap"

    # Core default
    orchestrator.set_global_threshold(3)
    assert orchestrator.get_effective_threshold(plugin, instance) == 3

    # Plugin override beats global
    orchestrator.set_plugin_threshold(plugin, 5)
    assert orchestrator.get_effective_threshold(plugin, instance) == 5

    # Instance override beats plugin + global
    orchestrator.set_instance_threshold(plugin, instance, 7)
    assert orchestrator.get_effective_threshold(plugin, instance) == 7


def test_layer4_threshold_blocks_crash_restarts_only(built_orchestrator):
    registry, state, orchestrator = built_orchestrator

    plugin = "ark"
    instance = "TestMap"

    orchestrator.set_global_threshold(1)

    ensure_ready(orchestrator, plugin, instance)
    orchestrator.start_instance(plugin, instance)
    assert state.get_state(plugin, instance) == "RUNNING"

    # First crash increments crash_total_count to 1 and should now pause crash restarts
    orchestrator._handle_event(
        plugin,
        {"event_type": "instance_crashed", "data": {"instance_id": instance}},
    )

    assert orchestrator.get_crash_total_count(plugin, instance) == 1
    assert orchestrator.is_crash_restart_paused(plugin, instance) is True
    assert state.get_state(plugin, instance) != "RUNNING"


def test_layer4_manual_start_allowed_after_crash_pause(built_orchestrator):
    registry, state, orchestrator = built_orchestrator

    plugin = "ark"
    instance = "TestMap"

    orchestrator.set_global_threshold(1)

    ensure_ready(orchestrator, plugin, instance)
    orchestrator.start_instance(plugin, instance)

    orchestrator._handle_event(
        plugin,
        {"event_type": "instance_crashed", "data": {"instance_id": instance}},
    )

    # Manual start should still be legal at the core gate (not DISABLED/illegal state).
    resp = orchestrator.start_instance(plugin, instance)
    if resp["status"] == "error":
        msg = str(resp.get("message") or "")
        assert "DISABLED" not in msg
        assert "Start not allowed in current state" not in msg


# ------------------------------------------------------------
# Layer 5 â€” DISABLED State Rules
# ------------------------------------------------------------

def test_layer5_disabled_blocks_all_restarts(built_orchestrator):
    registry, state, orchestrator = built_orchestrator

    plugin = "ark"
    instance = "TestMap"

    ensure_ready(orchestrator, plugin, instance)
    orchestrator.start_instance(plugin, instance)
    resp = orchestrator.disable_instance(plugin, instance, reason="test")
    assert resp["status"] == "success"
    assert state.get_state(plugin, instance) == "DISABLED"

    # Manual restart blocked
    r1 = orchestrator.restart_instance(plugin, instance, restart_reason="manual")
    assert r1["status"] != "success"

    # Crash restart blocked
    r2 = orchestrator.restart_instance(plugin, instance, restart_reason="crash")
    assert r2["status"] != "success"

    # Scheduled restart blocked (must block ALL restarts)
    r3 = orchestrator.restart_instance(plugin, instance, restart_reason="scheduled")
    assert r3["status"] != "success"


def test_layer5_disabled_blocks_start_no_reenable_yet(built_orchestrator):
    registry, state, orchestrator = built_orchestrator

    plugin = "ark"
    instance = "TestMap"

    ensure_ready(orchestrator, plugin, instance)
    orchestrator.start_instance(plugin, instance)
    orchestrator.disable_instance(plugin, instance, reason="test")
    assert state.get_state(plugin, instance) == "DISABLED"

    # Start should be refused (no re-enable flows yet)
    s = orchestrator.start_instance(plugin, instance)
    assert s["status"] != "success"


def test_layer5_manual_reenable_clears_disabled_and_resets_crash_count_no_autostart(built_orchestrator):
    registry, state, orchestrator = built_orchestrator

    plugin = "ark"
    instance = "TestMap"

    ensure_ready(orchestrator, plugin, instance)
    orchestrator.start_instance(plugin, instance)

    # Create a crash count
    orchestrator._handle_event(
        plugin,
        {"event_type": "instance_crashed", "data": {"instance_id": instance}},
    )
    assert orchestrator.get_crash_total_count(plugin, instance) >= 1

    # Disable it
    orchestrator.disable_instance(plugin, instance, reason="test")
    assert state.get_state(plugin, instance) == "DISABLED"

    # Re-enable should clear disabled and reset crash counter, but not start
    resp = orchestrator.reenable_instance(plugin, instance, reason="test")
    assert resp["status"] == "success"
    assert orchestrator.get_crash_total_count(plugin, instance) == 0
    assert state.get_state(plugin, instance) == "STOPPED"


def test_layer5_restart_allowed_after_reenable(built_orchestrator):
    registry, state, orchestrator = built_orchestrator

    plugin = "ark"
    instance = "TestMap"

    ensure_ready(orchestrator, plugin, instance)
    orchestrator.start_instance(plugin, instance)
    orchestrator.disable_instance(plugin, instance, reason="test")

    # Re-enable then start should be legal at the core gate.
    orchestrator.reenable_instance(plugin, instance, reason="test")
    ensure_ready(orchestrator, plugin, instance)
    s = orchestrator.start_instance(plugin, instance)
    if s["status"] == "error":
        msg = str(s.get("message") or "")
        assert "DISABLED" not in msg
        assert "Start not allowed in current state" not in msg
    if s["status"] == "success":
        assert state.get_state(plugin, instance) == "RUNNING"
