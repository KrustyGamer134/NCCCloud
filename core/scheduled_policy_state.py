from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


def scheduled_policy_state_path(cluster_root: str | None) -> Path | None:
    root = str(cluster_root or "").strip()
    if not root:
        return None
    return Path(root) / "state" / "scheduled_policy_state.json"


def load_scheduled_policy_state(cluster_root: str | None) -> Dict[str, Dict[str, str]]:
    path = scheduled_policy_state_path(cluster_root)
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    plugins = payload.get("plugins") if isinstance(payload, dict) else None
    if not isinstance(plugins, dict):
        return {}
    state: Dict[str, Dict[str, str]] = {}
    for plugin_name, raw in plugins.items():
        if not isinstance(raw, dict):
            continue
        plugin_state = {
            str(key): str(value).strip()
            for key, value in raw.items()
            if str(value or "").strip()
        }
        if plugin_state:
            state[str(plugin_name)] = plugin_state
    return state


def save_scheduled_policy_state(cluster_root: str | None, state: Dict[str, Dict[str, str]]) -> None:
    path = scheduled_policy_state_path(cluster_root)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "plugins": {
            str(plugin_name): {
                str(key): str(value).strip()
                for key, value in dict(values or {}).items()
                if str(value or "").strip()
            }
            for plugin_name, values in dict(state or {}).items()
            if isinstance(values, dict)
        }
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
