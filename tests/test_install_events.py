import json

from core.admin_api import AdminAPI
from core.orchestrator import Orchestrator
from core.state_manager import StateManager
from core.instance_layout import ensure_instance_layout, get_instance_root


class _StubConnection:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def send_request(self, action, payload):
        self.calls.append((action, payload))
        return dict(self._response)


class _StubRegistry:
    def __init__(self, connection):
        self._connection = connection

    def get(self, plugin_name):
        return {"connection": self._connection}

    def list_all(self):
        return ["ark"]


def _set_force_fail(cluster_root: str, plugin_name: str, instance_id: str, value: bool) -> None:
    ensure_instance_layout(cluster_root, plugin_name, instance_id)
    instance_root = get_instance_root(cluster_root, plugin_name, instance_id)
    meta_path = instance_root / "instance.json"

    with meta_path.open("r", encoding="utf-8") as f:
        meta = json.load(f)

    meta["force_install_fail"] = bool(value)

    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True)


def test_successful_install_emits_started_then_completed(tmp_path):
    cluster_root = str(tmp_path)

    conn = _StubConnection(response={"status": "success"})
    reg = _StubRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=cluster_root)

    orch.clear_events()

    # NEW: start no longer auto-installs (CG-PROVISION-2)
    resp_install = orch.install_instance("ark", "island")
    assert resp_install.get("status") == "success"

    # Start should succeed after install
    resp = orch.start_instance("ark", "island")
    assert resp.get("status") == "success"

    events = orch.get_events()
    types = [e.get("event_type") for e in events]

    assert "install_started" in types
    assert "install_completed" in types
    assert types.index("install_started") < types.index("install_completed")

    completed = next(e for e in events if e.get("event_type") == "install_completed")
    assert completed["plugin_name"] == "ark"
    assert completed["instance_id"] == "island"
    assert completed["payload"].get("install_status") == "INSTALLED"


def test_forced_failure_emits_started_then_failed(tmp_path):
    cluster_root = str(tmp_path)

    conn = _StubConnection(response={"status": "success"})
    reg = _StubRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=cluster_root)

    _set_force_fail(cluster_root, "ark", "island", True)

    orch.clear_events()

    # NEW: explicit install emits install_started/install_failed
    resp = orch.install_instance("ark", "island")
    assert resp.get("status") == "error"

    events = orch.get_events()
    types = [e.get("event_type") for e in events]

    assert "install_started" in types
    assert "install_failed" in types
    assert types.index("install_started") < types.index("install_failed")

    failed = next(e for e in events if e.get("event_type") == "install_failed")
    assert failed["plugin_name"] == "ark"
    assert failed["instance_id"] == "island"
    assert failed["payload"].get("install_status") == "FAILED"
    assert failed["payload"].get("reason") == "FORCED_FAILURE"


def test_no_install_events_on_status_reads(tmp_path):
    cluster_root = str(tmp_path)

    conn = _StubConnection(response={"status": "success"})
    reg = _StubRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=cluster_root)

    orch.clear_events()
    api = AdminAPI(orch)

    _ = api.get_instance_status("ark", "island")
    _ = api.get_scheduler_status()

    assert orch.get_events() == []