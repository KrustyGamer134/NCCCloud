

def test_orchestrator_stop_uses_runtime_summary_then_graceful_stop(built_orchestrator):
    _registry, state, orch = built_orchestrator

    actions = []

    def _fake_send_action(plugin_name, action, payload):
        actions.append(action)
        if action == "runtime_summary":
            return {"status": "success", "data": {"ok": True, "running": True, "ready": False}}
        if action == "graceful_stop":
            return {"status": "success", "data": {"ok": True, "simulated": False}}
        return {"status": "error", "data": {"ok": False}}

    orch.send_action = _fake_send_action

    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.RUNNING)

    res = orch.stop_instance("ark", "10")
    assert res.get("status") == "success"
    assert actions == ["runtime_summary", "graceful_stop", "runtime_summary"]


def test_orchestrator_restart_calls_graceful_stop_then_runtime_check_then_start(built_orchestrator):
    _registry, state, orch = built_orchestrator

    actions = []
    runtime_checks = iter([True, False, True])

    def _fake_send_action(plugin_name, action, payload):
        actions.append(action)
        if action == "runtime_summary":
            return {"status": "success", "data": {"ok": True, "running": next(runtime_checks), "ready": True}}
        if action == "graceful_stop":
            return {"status": "success", "data": {"ok": True, "stopped": True, "simulated": False}}
        return {"status": "success", "data": {}}

    orch.send_action = _fake_send_action
    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.RUNNING)

    res = orch.restart_instance("ark", "10", restart_reason="manual")
    assert res.get("status") == "success"
    assert actions == ["runtime_summary", "graceful_stop", "runtime_summary", "start", "runtime_summary"]
    assert state.get_state("ark", "10") == state.RUNNING


def test_restart_rejected_when_server_is_still_shutting_down(built_orchestrator):
    _registry, state, orch = built_orchestrator

    actions = []

    def _fake_send_action(plugin_name, action, payload):
        actions.append(action)
        if action == "runtime_summary":
            return {"status": "success", "data": {"ok": True, "running": True, "ready": False}}
        if action == "graceful_stop":
            return {"status": "success", "data": {"ok": True, "stopped": False, "simulated": False}}
        return {"status": "success", "data": {}}

    orch.send_action = _fake_send_action
    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.RUNNING)

    res = orch.restart_instance("ark", "10", restart_reason="manual")
    assert res.get("status") == "error"
    assert res.get("message") == "Server is still shutting down."
    assert actions == ["runtime_summary", "graceful_stop", "runtime_summary"]
    assert state.get_state("ark", "10") == state.RESTARTING


def test_stop_rejected_when_runtime_summary_reports_not_running(built_orchestrator):
    _registry, state, orch = built_orchestrator

    actions = []

    def _fake_send_action(plugin_name, action, payload):
        actions.append(action)
        if action == "runtime_summary":
            return {"status": "success", "data": {"ok": True, "running": False, "ready": False}}
        if action == "graceful_stop":
            return {"status": "success", "data": {"ok": True, "simulated": False}}
        return {"status": "error", "data": {"ok": False}}

    orch.send_action = _fake_send_action

    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.RUNNING)

    res = orch.stop_instance("ark", "10")
    assert res.get("status") == "error"
    assert res.get("message") == "Server is not running."
    assert actions == ["runtime_summary"]


def test_stop_while_stopped_allowed_when_runtime_summary_reports_running(built_orchestrator):
    _registry, state, orch = built_orchestrator

    actions = []

    def _fake_send_action(plugin_name, action, payload):
        actions.append(action)
        if action == "runtime_summary":
            return {"status": "success", "data": {"ok": True, "running": True, "ready": False}}
        if action == "graceful_stop":
            return {"status": "success", "data": {"ok": True, "simulated": False}}
        return {"status": "error", "data": {"ok": False}}

    orch.send_action = _fake_send_action

    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.STOPPED)

    res = orch.stop_instance("ark", "10")
    assert res.get("status") == "success"
    assert actions == ["runtime_summary", "graceful_stop", "runtime_summary"]
    assert state.get_state("ark", "10") == state.STOPPING


def test_stop_disabled_still_blocked_without_probe(built_orchestrator):
    _registry, state, orch = built_orchestrator

    actions = []

    def _fake_send_action(plugin_name, action, payload):
        actions.append(action)
        return {"status": "success", "data": {"ok": True, "running": True, "simulated": False}}

    orch.send_action = _fake_send_action

    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.DISABLED)

    res = orch.stop_instance("ark", "10")
    assert res.get("status") == "error"
    assert "DISABLED" in res.get("message", "")
    assert actions == []


def test_restart_rejected_when_runtime_summary_reports_not_running(built_orchestrator):
    _registry, state, orch = built_orchestrator

    actions = []

    def _fake_send_action(plugin_name, action, payload):
        actions.append(action)
        if action == "runtime_summary":
            return {"status": "success", "data": {"ok": True, "running": False, "ready": False}}
        return {"status": "success", "data": {"ok": True, "simulated": False}}

    orch.send_action = _fake_send_action

    state.ensure_instance_exists("ark", "10")
    state.set_state("ark", "10", state.RUNNING)

    res = orch.restart_instance("ark", "10", restart_reason="manual")
    assert res.get("status") == "error"
    assert res.get("message") == "Server is not running."
    assert actions == ["runtime_summary"]
