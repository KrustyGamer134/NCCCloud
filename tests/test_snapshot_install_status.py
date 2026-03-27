from core.admin_api import AdminAPI


class _StubOrchestrator:
    class _SM:
        STOPPED = "STOPPED"
        DISABLED = "DISABLED"

    def __init__(
        self,
        runtime_running=False,
        runtime_ready=False,
        core_state="STOPPED",
        install_status="NOT_INSTALLED",
        last_action=None,
    ):
        self._state_manager = self._SM()
        self._runtime_running = bool(runtime_running)
        self._runtime_ready = bool(runtime_ready)
        self._core_state = str(core_state)
        self._install_status = str(install_status)
        self._last_action = None if last_action is None else str(last_action)

    def get_instance_state(self, plugin_name, instance_id):
        return self._core_state

    def get_instance_last_action(self, plugin_name, instance_id):
        return self._last_action

    def get_instance_disabled_state(self, plugin_name, instance_id):
        return False

    def get_crash_total_count(self, plugin_name, instance_id):
        return 0

    def get_crash_stability_count(self, plugin_name, instance_id):
        return 0

    def get_effective_threshold(self, plugin_name, instance_id):
        return 3

    def is_crash_restart_paused(self, plugin_name, instance_id):
        return False

    def get_instance_install_status(self, plugin_name, instance_id):
        return self._install_status

    def send_action(self, plugin_name, action, payload=None):
        if action == "runtime_summary":
            return {
                "status": "success",
                "data": {
                    "ok": True,
                    "running": bool(self._runtime_running),
                    "ready": bool(self._runtime_ready),
                },
            }
        return {"status": "error", "data": {"ok": False}}

    def read_cached_runtime_summary(self, plugin_name, instance_id):
        return self.send_action(plugin_name, "runtime_summary", {"instance_id": str(instance_id)})


def test_admin_instance_status_includes_install_status_and_stopped_mapping():
    api = AdminAPI(_StubOrchestrator())
    snap = api.get_instance_status("ark", "island")
    assert snap["install_status"] == "NOT_INSTALLED"
    assert snap["state"] == "STOPPED"
    assert snap["core_state"] == "STOPPED"
    assert snap["effective_state"] == "STOPPED"
    assert snap["runtime_running"] is False
    assert snap["runtime_ready"] is False


def test_admin_instance_status_maps_start_to_starting():
    api = AdminAPI(_StubOrchestrator(runtime_running=True, runtime_ready=False, core_state="RUNNING", last_action="start"))
    snap = api.get_instance_status("ark", "island")
    assert snap["runtime_running"] is True
    assert snap["runtime_ready"] is False
    assert snap["effective_state"] == "STARTING"
    assert snap["state"] == "STARTING"


def test_admin_instance_status_maps_runtime_ready_to_started():
    api = AdminAPI(_StubOrchestrator(runtime_running=True, runtime_ready=True, core_state="RUNNING", last_action="start"))
    snap = api.get_instance_status("ark", "island")
    assert snap["runtime_running"] is True
    assert snap["runtime_ready"] is True
    assert snap["effective_state"] == "STARTED"
    assert snap["state"] == "STARTED"


def test_admin_instance_status_maps_stop_to_stopping_while_running():
    api = AdminAPI(_StubOrchestrator(runtime_running=True, runtime_ready=False, core_state="STOPPING", last_action="stop"))
    snap = api.get_instance_status("ark", "island")
    assert snap["state"] == "STOPPING"


def test_admin_instance_status_maps_restart_to_restarting_until_ready():
    api = AdminAPI(_StubOrchestrator(runtime_running=True, runtime_ready=False, core_state="RUNNING", last_action="restart"))
    snap = api.get_instance_status("ark", "island")
    assert snap["state"] == "RESTARTING"


def test_admin_cached_instance_status_does_not_reconcile_stop_progress():
    class _ReconcilingOrchestrator(_StubOrchestrator):
        def __init__(self):
            super().__init__()
            self.reconcile_calls = []

        def reconcile_stop_progress(self, plugin_name, instance_id):
            self.reconcile_calls.append((plugin_name, instance_id))

    orch = _ReconcilingOrchestrator()
    api = AdminAPI(orch)

    snap = api.read_cached_instance_status("ark", "island")

    assert snap["state"] == "STOPPED"
    assert orch.reconcile_calls == []


def test_admin_refresh_instance_status_reconciles_stop_progress():
    class _ReconcilingOrchestrator(_StubOrchestrator):
        def __init__(self):
            super().__init__()
            self.reconcile_calls = []

        def reconcile_stop_progress(self, plugin_name, instance_id):
            self.reconcile_calls.append((plugin_name, instance_id))

    orch = _ReconcilingOrchestrator()
    api = AdminAPI(orch)

    snap = api.refresh_instance_status("ark", "island")

    assert snap["state"] == "STOPPED"
    assert orch.reconcile_calls == [("ark", "island")]
