import json

from core.admin_api import AdminAPI
from core.orchestrator import Orchestrator
from core.state_manager import StateManager
from core.instance_layout import ensure_instance_layout, get_instance_root, read_instance_install_status


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
        # Needed for any flows that enumerate plugins
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


def test_forced_install_failure_aborts_start_and_sets_failed(tmp_path):
    cluster_root = str(tmp_path)

    conn = _StubConnection(response={"status": "success", "data": {"ok": True, "simulated": False}})
    reg = _StubRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=cluster_root)

    _set_force_fail(cluster_root, "ark", "island", True)

    # CG-PROVISION-2: install is explicit; start must NOT auto-install
    resp_install = orch.install_instance("ark", "island")
    assert resp_install.get("status") == "error"

    # Lifecycle state must remain STOPPED
    assert state.get_state("ark", "island") == state.STOPPED

    # Ensure no plugin start request happened (install never starts server)
    assert conn.calls == []

    # Metadata must show FAILED
    assert read_instance_install_status(cluster_root, "ark", "island") == "FAILED"

    # Snapshot must reflect FAILED
    api = AdminAPI(orch)
    snap = api.get_instance_status("ark", "island")
    assert snap["install_status"] == "FAILED"

    # Start must still refuse until installed
    resp_start = orch.start_instance("ark", "island")
    assert resp_start.get("status") == "error"


def test_failure_removed_allows_start_to_proceed(tmp_path):
    cluster_root = str(tmp_path)

    conn = _StubConnection(response={"status": "success", "data": {"ok": True, "simulated": False}})
    reg = _StubRegistry(conn)
    state = StateManager(state_file=None)
    orch = Orchestrator(reg, state, cluster_root=cluster_root)

    # First: force failure
    _set_force_fail(cluster_root, "ark", "island", True)
    resp1 = orch.install_instance("ark", "island")
    assert resp1.get("status") == "error"
    assert state.get_state("ark", "island") == state.STOPPED
    assert conn.calls == []
    assert read_instance_install_status(cluster_root, "ark", "island") == "FAILED"

    # Second: remove failure and install again
    _set_force_fail(cluster_root, "ark", "island", False)
    resp2 = orch.install_instance("ark", "island")
    assert resp2.get("status") == "success"
    assert read_instance_install_status(cluster_root, "ark", "island") == "INSTALLED"

    # Now start should proceed to plugin boundary and succeed
    resp3 = orch.start_instance("ark", "island")
    assert resp3.get("status") == "success"
    assert ("start", {"instance_id": "island"}) in conn.calls
    assert state.get_state("ark", "island") == state.RUNNING
