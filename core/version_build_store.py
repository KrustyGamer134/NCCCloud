from __future__ import annotations

import json
import os
from pathlib import Path


def resolve_version_build_map_path(*, cluster_root: str, gameservers_root: str) -> str | None:
    gameservers_text = str(gameservers_root or "").strip()
    if gameservers_text:
        return str(Path(gameservers_text) / ".ncc" / "version_build_map.json")
    cluster_text = str(cluster_root or "").strip()
    if not cluster_text:
        return None
    return str(Path(cluster_text) / ".ncc" / "version_build_map.json")


def load_version_build_plugins_state(path: str | None) -> dict:
    if not path or not os.path.isfile(path):
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    plugins = payload.get("plugins")
    return plugins if isinstance(plugins, dict) else {}


def save_version_build_plugins_state(path: str | None, plugins: dict) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(target.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps({"plugins": plugins}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(str(tmp_path), str(target))
