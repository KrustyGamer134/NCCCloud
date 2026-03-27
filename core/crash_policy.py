############################################################
# SECTION: Crash Policy
# Purpose:
#     Crash counter storage, threshold management, and
#     crash-restart pause derivation.
# Lifecycle Ownership:
#     Orchestrator (Core)
# Phase:
#     Crash Architecture - Phase 2/3 (Dual Counters + Thresholds)
# Constraints:
#     - Memory only (no persistence of its own)
#     - No lifecycle transitions
#     - No scheduler interaction
############################################################


from __future__ import annotations


class CrashPolicy:

    def __init__(self, default_threshold: int = 3):
        # Dual counters: (plugin_name, instance_id) -> {crash_total_count, crash_stability_count}
        self._crash_counters: dict[tuple[str, str], dict[str, int]] = {}

        # Threshold overrides
        self._global_threshold = default_threshold
        self._plugin_thresholds: dict[str, int] = {}
        self._instance_thresholds: dict[tuple[str, str], int] = {}

        # Instances whose crash count has hit threshold (restart suppressed)
        self._crash_restart_paused: set[tuple[str, str]] = set()

    # ------------------------------------------------------------------
    # Counter internals
    # ------------------------------------------------------------------

    def _ensure_counter_entry(self, plugin_name, instance_id):
        key = (plugin_name, instance_id)
        if key not in self._crash_counters:
            self._crash_counters[key] = {
                "crash_total_count": 0,
                "crash_stability_count": 0,
            }
        return key

    # ------------------------------------------------------------------
    # Counter read API
    # ------------------------------------------------------------------

    def get_crash_total_count(self, plugin_name, instance_id):
        key = (plugin_name, instance_id)
        if key not in self._crash_counters:
            return 0
        return self._crash_counters[key]["crash_total_count"]

    def get_crash_stability_count(self, plugin_name, instance_id):
        key = (plugin_name, instance_id)
        if key not in self._crash_counters:
            return 0
        return self._crash_counters[key]["crash_stability_count"]

    def reset_crash_total_count(self, plugin_name, instance_id):
        key = self._ensure_counter_entry(plugin_name, instance_id)
        self._crash_counters[key]["crash_total_count"] = 0

    def reset_stability_for_plugin(self, plugin_name):
        for (p, i), data in self._crash_counters.items():
            if p == plugin_name:
                data["crash_stability_count"] = 0

    def reset_stability_count(self, plugin_name, instance_id):
        key = self._ensure_counter_entry(plugin_name, instance_id)
        self._crash_counters[key]["crash_stability_count"] = 0

    # ------------------------------------------------------------------
    # Threshold management
    # ------------------------------------------------------------------

    def set_global_threshold(self, value):
        self._global_threshold = int(value)

    def set_plugin_threshold(self, plugin_name, value):
        self._plugin_thresholds[plugin_name] = int(value)

    def set_instance_threshold(self, plugin_name, instance_id, value):
        self._instance_thresholds[(plugin_name, instance_id)] = int(value)

    def get_effective_threshold(self, plugin_name, instance_id):
        key = (plugin_name, instance_id)
        if key in self._instance_thresholds:
            return self._instance_thresholds[key]
        if plugin_name in self._plugin_thresholds:
            return self._plugin_thresholds[plugin_name]
        return self._global_threshold

    # ------------------------------------------------------------------
    # Pause state
    # ------------------------------------------------------------------

    def is_crash_restart_paused(self, plugin_name, instance_id):
        return (plugin_name, instance_id) in self._crash_restart_paused

    def record_crash(self, plugin_name, instance_id):
        """Increment counters and return True if the threshold is now reached."""
        key = self._ensure_counter_entry(plugin_name, instance_id)
        self._crash_counters[key]["crash_total_count"] += 1
        self._crash_counters[key]["crash_stability_count"] += 1
        threshold = self.get_effective_threshold(plugin_name, instance_id)
        if self._crash_counters[key]["crash_total_count"] >= threshold:
            self._crash_restart_paused.add((plugin_name, instance_id))
            return True
        return False

    def clear_pause(self, plugin_name, instance_id):
        self._crash_restart_paused.discard((plugin_name, instance_id))

    # ------------------------------------------------------------------
    # Persistence snapshot / restore helpers
    # ------------------------------------------------------------------

    def build_snapshot(self, encode_key_fn):
        """Return serialisable dicts for persistence."""
        crash_counters = {}
        for (plugin_name, instance_id), data in self._crash_counters.items():
            crash_counters[encode_key_fn(plugin_name, instance_id)] = {
                "crash_total_count": int(data.get("crash_total_count", 0)),
                "crash_stability_count": int(data.get("crash_stability_count", 0)),
            }

        thresholds = {
            "global": int(self._global_threshold),
            "plugins": {k: int(v) for k, v in self._plugin_thresholds.items()},
            "instances": {
                encode_key_fn(p, i): int(v)
                for (p, i), v in self._instance_thresholds.items()
            },
        }
        return {"crash_counters": crash_counters, "thresholds": thresholds}

    def restore_snapshot(self, snapshot, decode_key_fn):
        """Restore counters and thresholds from a persisted snapshot dict."""
        self._crash_counters = {}
        for encoded_key, data in (snapshot.get("crash_counters") or {}).items():
            plugin_name, instance_id = decode_key_fn(encoded_key)
            self._crash_counters[(plugin_name, instance_id)] = {
                "crash_total_count": int(data.get("crash_total_count", 0)),
                "crash_stability_count": int(data.get("crash_stability_count", 0)),
            }

        thresholds = snapshot.get("thresholds") or {}
        if "global" in thresholds:
            self._global_threshold = int(thresholds["global"])
        self._plugin_thresholds = {
            k: int(v) for k, v in (thresholds.get("plugins") or {}).items()
        }
        self._instance_thresholds = {}
        for encoded_key, v in (thresholds.get("instances") or {}).items():
            p, i = decode_key_fn(encoded_key)
            self._instance_thresholds[(p, i)] = int(v)

    def derive_pause_from_counters(self, get_disabled_fn, get_threshold_fn):
        """Rebuild _crash_restart_paused deterministically after a restore."""
        self._crash_restart_paused = set()
        for (plugin_name, instance_id), data in self._crash_counters.items():
            if get_disabled_fn(plugin_name, instance_id):
                continue
            total = int(data.get("crash_total_count", 0))
            threshold = int(get_threshold_fn(plugin_name, instance_id))
            if total >= threshold:
                self._crash_restart_paused.add((plugin_name, instance_id))
