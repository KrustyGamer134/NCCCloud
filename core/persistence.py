import json
import os
from typing import Any, Dict


class CorePersistence:
    """
    Durability-only persistence for Core-owned lifecycle state and crash metadata.

    Atomic write:
      - write to temp file
      - flush + fsync
      - os.replace -> atomic rename/replace
    """

    SCHEMA_VERSION = 2  # bumped for restart_metadata

    def __init__(self, path: str):
        self._path = path

    @property
    def path(self) -> str:
        return self._path

    def exists(self) -> bool:
        return self._path is not None and os.path.exists(self._path)

    def load(self) -> Dict[str, Any]:
        with open(self._path, "r", encoding="utf-8") as f:
            data = json.load(f)

        version = data.get("schema_version")

        # Backward compatible: accept v1 (no restart_metadata)
        if version == 1:
            data.setdefault("restart_metadata", {})
            return data

        if version != self.SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema_version: {version}")

        # Shape validation (lightweight)
        if "lifecycle" not in data or "crash_counters" not in data or "thresholds" not in data:
            raise ValueError("Invalid persistence payload: missing required top-level keys")

        data.setdefault("restart_metadata", {})
        return data

    def save(self, snapshot: Dict[str, Any]) -> None:
        if self._path is None:
            raise ValueError("Persistence path is None; cannot save")

        directory = os.path.dirname(self._path) or "."
        os.makedirs(directory, exist_ok=True)

        tmp_path = self._path + ".tmp"

        payload = dict(snapshot)
        payload["schema_version"] = self.SCHEMA_VERSION

        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True, ensure_ascii=True)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, self._path)