from __future__ import annotations

from core.orchestrator import Orchestrator
from core.state_manager import StateManager


class _Registry:
    def list_all(self):
        return ["ark"]

    def get_metadata(self, plugin_name):
        return {
            "dependencies": [
                {
                    "id": "vcredist_2013_x64",
                    "label": "Microsoft Visual C++ 2013 Redistributable x64",
                    "type": "windows_component",
                    "field": "vcredist_2013_x64",
                    "guidance": {
                        "message": "Install Microsoft Visual C++ 2013 Redistributable (x64) on this Windows server."
                    },
                },
                {
                    "id": "directx_june_2010",
                    "label": "DirectX End-User Runtimes (June 2010)",
                    "type": "windows_component",
                    "field": "directx_june_2010",
                    "guidance": {
                        "message": "Install DirectX End-User Runtimes (June 2010) on this Windows server."
                    },
                },
            ]
        }

    def get(self, plugin_name):
        return None


def test_windows_component_dependencies_use_core_checks_and_guidance(tmp_path, monkeypatch):
    orch = Orchestrator(_Registry(), StateManager(state_file=None), cluster_root=str(tmp_path))

    def fake_check(component_id):
        if component_id == "vcredist_2013_x64":
            return True, r"C:\Windows\System32\msvcr120.dll"
        if component_id == "directx_june_2010":
            return False, r"C:\Windows\System32\XAudio2_7.dll"
        raise AssertionError(f"unexpected component id: {component_id}")

    monkeypatch.setattr(orch, "_check_windows_component", fake_check)
    report = orch.get_plugin_dependency_report("ark")

    results = report["plugins"]["ark"]["results"]
    assert results[0]["status"] == "installed"
    assert results[0]["details"] == r"C:\Windows\System32\msvcr120.dll"
    assert results[1]["status"] == "missing"
    assert results[1]["details"] == "Install DirectX End-User Runtimes (June 2010) on this Windows server."
    assert report["plugins"]["ark"]["status"] == "missing"
