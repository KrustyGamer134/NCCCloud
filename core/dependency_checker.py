############################################################
# SECTION: Dependency Checker
# Purpose:
#     Windows component checks and the app dependency state
#     store (persisted JSON tracking install_failed entries).
#     Called by the Orchestrator for all dependency evaluation.
# Lifecycle Ownership:
#     Orchestrator (Core)
# Phase:
#     Core v1.2 - Deterministic Lifecycle
# Constraints:
#     - No lifecycle transitions
#     - No thread/async
############################################################

import json
import os


class DependencyChecker:

    def __init__(self, get_cluster_root_fn, on_state_changed_fn):
        self._get_cluster_root = get_cluster_root_fn
        self._on_state_changed = on_state_changed_fn

    def _state_path(self):
        from pathlib import Path
        cluster_root = self._get_cluster_root()
        if not cluster_root:
            return None
        return Path(str(cluster_root)) / "state" / "app_dependency_state.json"

    def _load_state_map(self):
        path = self._state_path()
        if path is None or not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_state_map(self, payload):
        path = self._state_path()
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def read_state(self, dep_id):
        payload = self._load_state_map()
        item = payload.get(str(dep_id))
        if not isinstance(item, dict):
            return ""
        if str(item.get("status") or "").strip().lower() != "install_failed":
            return ""
        return str(item.get("details") or "").strip()

    def set_failed(self, dep_id, details):
        payload = self._load_state_map()
        payload[str(dep_id)] = {
            "status": "install_failed",
            "details": str(details or "").strip(),
        }
        self._write_state_map(payload)
        self._on_state_changed(dep_id)

    def clear(self, dep_id):
        payload = self._load_state_map()
        if str(dep_id) in payload:
            payload.pop(str(dep_id), None)
            self._write_state_map(payload)
        self._on_state_changed(dep_id)

    def check_windows_component(self, component_id):
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        system32 = os.path.join(system_root, "System32")
        checks = {
            "vcredist_2013_x64": [
                os.path.join(system32, "msvcr120.dll"),
                os.path.join(system32, "msvcp120.dll"),
            ],
            "directx_june_2010": [
                os.path.join(system32, "XAudio2_7.dll"),
                os.path.join(system32, "D3DCompiler_43.dll"),
                os.path.join(system32, "XInput1_3.dll"),
            ],
        }
        wanted = checks.get(str(component_id))
        if not wanted:
            return False, ""
        for path in wanted:
            if not os.path.isfile(path):
                return False, path
        return True, wanted[0]

    def evaluate_windows_component(self, dep_id, label, component_id, guidance):
        message = str((guidance or {}).get("message") or "").strip()
        if os.name != "nt":
            details = message or "Windows-only dependency check."
            return {"id": dep_id, "label": label, "status": "missing",
                    "details": details, "guidance": guidance}
        ok, detail = self.check_windows_component(component_id)
        if ok:
            return {"id": dep_id, "label": label, "status": "installed",
                    "details": str(detail or component_id), "guidance": guidance}
        details = message or str(detail or component_id)
        return {"id": dep_id, "label": label, "status": "missing",
                "details": details, "guidance": guidance}
