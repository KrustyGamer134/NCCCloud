from pathlib import Path

from core.orchestrator import Orchestrator
from core.state_manager import StateManager


class _Registry:
    def get(self, plugin_name):
        return None

    def list_all(self):
        return []


def test_instance_readiness_report_reuses_cache_until_dirty(tmp_path: Path, monkeypatch):
    orch = Orchestrator(_Registry(), StateManager(state_file=None), cluster_root=str(tmp_path))
    calls = []

    def _send_action(plugin_name, action, payload=None):
        calls.append((str(plugin_name), str(action), dict(payload or {})))
        return {
            "status": "success",
            "data": {
                "checks": [
                    {"id": "launch_required_fields", "ok": False, "details": "missing required launch fields: map"},
                    {"id": "bootstrap_ini", "ok": False, "details": "ignored"},
                ]
            },
        }

    monkeypatch.setattr(orch, "send_action", _send_action)

    first = orch.get_instance_readiness_report("ark", "10")
    second = orch.get_instance_readiness_report("ark", "10")

    assert first["status"] == "missing"
    assert [item["label"] for item in first["results"]] == ["launch_required_fields"]
    assert second == first
    assert calls == [("ark", "validate", {"instance_id": "10", "strict": True, "live_probe": False})]

    orch._mark_instance_readiness_dirty("ark", "10")
    third = orch.get_instance_readiness_report("ark", "10")

    assert third["status"] == "missing"
    assert third == first
    assert calls == [("ark", "validate", {"instance_id": "10", "strict": True, "live_probe": False})]

    refreshed = orch.refresh_instance_readiness_report("ark", "10")

    assert refreshed["status"] == "missing"
    assert calls == [
        ("ark", "validate", {"instance_id": "10", "strict": True, "live_probe": False}),
        ("ark", "validate", {"instance_id": "10", "strict": True, "live_probe": False}),
    ]


def test_instance_readiness_report_install_result_invalidates_cache(tmp_path: Path, monkeypatch):
    orch = Orchestrator(_Registry(), StateManager(state_file=None), cluster_root=str(tmp_path))
    orch._cached_instance_readiness_reports[("ark", "10")] = {
        "ok": True,
        "plugin_name": "ark",
        "instance_id": "10",
        "status": "installed",
        "results": [],
    }

    monkeypatch.setattr("core.orchestrator.ensure_installed", lambda cluster_root, plugin_name, instance_id: {"status": "INSTALLED"})

    resp = orch.install_instance("ark", "10")

    assert resp["status"] == "success"
    assert ("ark", "10") in orch._dirty_instance_readiness
