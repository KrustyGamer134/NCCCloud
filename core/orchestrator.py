############################################################
# SECTION: Orchestrator Core Authority
# Purpose:
#     Central lifecycle authority for all plugin interaction.
# Lifecycle Ownership:
#     Core
# Phase:
#     Core v1.2 - Deterministic Lifecycle
# Constraints:
#     - Core decides, plugins execute
#     - Must not execute OS-level server logic
#     - Must not bypass PluginRegistry
############################################################
from core.scheduler_engine import SchedulerEngine
from core.persistence import CorePersistence
from core.installer import ensure_installed
from core.version_build_store import (
    load_version_build_plugins_state,
    resolve_version_build_map_path,
    save_version_build_plugins_state,
)
from core.scheduled_policy_state import (
    load_scheduled_policy_state,
    save_scheduled_policy_state,
)
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any
from datetime import datetime

from core.port_check import check_ports_availability
from core.plugin_config import (
    PluginConfigError,
    legacy_instance_config_path,
    load_plugin_defaults,
    load_instance_config,
    instance_config_path,
    resolve_instance_config_path,
    ensure_plugin_defaults_file,
    write_instance_config_atomic,
    compute_effective_mods,
)


from core.events import (
    build_event,
    EVENT_INSTANCE_STARTED,
    EVENT_INSTANCE_STOPPED,
    EVENT_INSTANCE_RESTARTED,
    EVENT_INSTANCE_DISABLED,
    EVENT_INSTANCE_ENABLED,
    EVENT_INSTANCE_CRASHED,
    EVENT_CRASH_THRESHOLD_REACHED,
    EVENT_INSTALL_STARTED,
    EVENT_INSTALL_COMPLETED,
    EVENT_INSTALL_FAILED,
    EVENT_INSTANCE_VERSION_ADVANCED,
)

_STOPPING_FORCE_TIMEOUT_SECONDS = 30.0
_DEFAULT_UPDATE_WARNING_MINUTES = 5
_DEFAULT_UPDATE_WARNING_INTERVAL_MINUTES = 1
_RUNTIME_SUMMARY_MIN_REFRESH_SECONDS = 0.5
_DEEP_RUNTIME_INSPECT_MIN_REFRESH_SECONDS = 1.0
_STARTUP_INI_SYNC_FIELDS = [
    "mods",
    "passive_mods",
    "max_players",
    "game_port",
    "rcon_port",
    "rcon_enabled",
    "admin_password",
    "server_name",
    "display_name",
    "pve",
]

class Orchestrator:
    # SECTION: Initialization
    ############################################################
    def __init__(self, plugin_registry, state_manager, persistence_path=None, cluster_root=None):
        ...
        self._cluster_root = cluster_root
        self._registry = plugin_registry
        self._state_manager = state_manager
        self._scheduler = SchedulerEngine(self)
        self._plugin_thresholds = {}
        self._crash_restart_paused = set()
        self._event_log = []
        self._event_clock = 0
        self._instance_last_action = {}
        self._stop_deadlines = {}
        # Readiness ownership lives in the orchestrator. UI/AdminAPI read from
        # these caches; only explicit refresh paths recompute them.
        self._cached_app_setup_report = None
        self._app_setup_dirty = True
        self._cached_plugin_readiness_reports = {}
        self._plugin_readiness_dirty_all = False
        self._dirty_plugin_readiness = set()
        self._cached_instance_readiness_reports = {}
        self._instance_readiness_dirty_all = False
        self._dirty_instance_readiness = set()
        self._dirty_instance_readiness_plugins = set()
        # Runtime ownership also lives in the orchestrator. Summary is the
        # lightweight poll surface; inspect is the explicit deep probe surface.
        self._cached_runtime_summaries = {}
        self._runtime_summary_last_updated = {}
        self._runtime_summary_inflight = set()
        self._cached_runtime_inspects = {}
        self._runtime_inspect_last_updated = {}
        self._runtime_inspect_inflight = set()
        self._version_build_map = {}
        self._version_build_state = {}
        self._pending_update_verifications = {}
        self._pending_update_verification_notifications = {}
        self._scheduled_policy_state = load_scheduled_policy_state(cluster_root)
        self._load_version_build_map()


        ############################################################
        # SECTION: Dual Crash Counter Storage
        # Purpose:
        # Store per-instance crash_total_count and crash_stability_count.
        # Lifecycle Ownership:
        # Orchestrator (Core)
        # Phase:
        # Crash Architecture - Phase 2 (Dual Counters)
        # Constraints:
        # - Memory only.
        # - No threshold logic.
        # - No disable logic.
        ############################################################
        self._crash_counters = {}

        # ----------------------------
        # Layer 7-3: Last Restart Metadata (deterministic logical time)
        # ----------------------------
        self._last_restart_metadata = {}  # (plugin, instance) -> {"last_restart_source": str, "last_restart_time": int}
        self._restart_clock = 0

        ############################################################
        # SECTION: Threshold Storage
        # Purpose:
        # Store global and per-instance crash thresholds.
        # Lifecycle Ownership:
        # Orchestrator (Core)
        # Phase:
        # Crash Architecture - Phase 3 (Threshold Enforcement)
        # Constraints:
        # - No persistence.
        # - No time windows.
        # - No backoff logic.
        ############################################################
        self._global_threshold = 3
        self._instance_thresholds = {}

        # ----------------------------
        # Layer 6: Durability only
        # ----------------------------
        self._persistence = CorePersistence(persistence_path) if persistence_path else None
        if self._persistence and self._persistence.exists():
            self._restore_from_persistence()

    ############################################################
    # SECTION: Internal Event Emission
    ############################################################

    def _emit_event(self, event_type, plugin_name=None, instance_id=None, payload=None):
        event = build_event(
            event_type=event_type,
            logical_timestamp=self._event_clock,
            plugin_name=plugin_name,
            instance_id=instance_id,
            payload=payload,
        )
        self._event_log.append(event)
        self._event_clock += 1

    def get_events(self):
        return list(self._event_log)

    def clear_events(self):
        self._event_log.clear()

    ############################################################
    # SECTION: Layer 6-2 Crash Pause Derivation
    # Purpose:
    # Derive crash-restart pause state from persisted counters
    # and resolved thresholds.
    # Lifecycle Ownership:
    # Orchestrator (Core)
    # Phase:
    # Layer 6-2 (Derivation Only)
    # Constraints:
    # - No lifecycle transitions
    # - No restart execution
    # - No scheduler interaction
    # - No persistence of pause flags
    ############################################################
    def _derive_crash_restart_paused_from_persisted_state(self) -> None:

        # Rebuild pause set deterministically
        self._crash_restart_paused = set()

        for (plugin_name, instance_id), data in self._crash_counters.items():

            # DISABLED remains sole authority for blocking restarts
            if self.get_instance_disabled_state(plugin_name, instance_id):
                continue

            total = int(data.get("crash_total_count", 0))
            threshold = int(self.get_effective_threshold(plugin_name, instance_id))

            if total >= threshold:
                self._crash_restart_paused.add((plugin_name, instance_id))



    def reset_stability_for_plugin(self, plugin_name):
        for (p, i), data in self._crash_counters.items():
            if p == plugin_name:
                data["crash_stability_count"] = 0

    def notify_plugin_window_open(self, plugin_name):
        pass

    def notify_plugin_window_close(self, plugin_name):
        pass

    ############################################################
    # SECTION: Scheduler Inspection API
    # Purpose:
    # Provide read-only access to SchedulerEngine state.
    # Lifecycle Ownership:
    # Orchestrator (Core)
    # Phase:
    # Scheduled Restart Architecture - Phase 4A (Control Plane)
    # Constraints:
    # - Read-only exposure only.
    # - No internal state mutation.
    ############################################################

    def is_maintenance_active(self):
        return self._scheduler.is_maintenance_active()

    def is_maintenance_paused(self):
        return self._scheduler.is_maintenance_paused()

    def is_maintenance_failed(self):
        return self._scheduler.is_maintenance_failed()

    def is_crash_restart_paused(self, plugin_name, instance_id):
        return (plugin_name, instance_id) in self._crash_restart_paused

    def get_current_maintenance_plugin(self):
        return self._scheduler.get_current_plugin()

    def get_failed_plugin_count(self):
        return self._scheduler.get_failed_plugin_count()

    def get_escalation_threshold(self):
        return self._scheduler.get_escalation_threshold()

    def get_next_window_time(self):
        return self._scheduler.get_next_window_time()

    def get_plugin_last_window_duration(self, plugin_name):
        return self._scheduler.get_plugin_last_window_duration(plugin_name)

    def tick_scheduled_tasks(self, current_datetime=None):
        now = current_datetime if isinstance(current_datetime, datetime) else self._current_datetime()
        results = {"update_checks": [], "scheduled_restarts": [], "notifications": []}
        for plugin_name in [str(name) for name in self.list_plugins()]:
            update_result = self._run_scheduled_update_check(plugin_name, now)
            if isinstance(update_result, dict):
                results["update_checks"].append(update_result)
                notifications = update_result.get("notifications")
                if isinstance(notifications, list):
                    results["notifications"].extend([dict(item) for item in notifications if isinstance(item, dict)])
            restart_result = self._run_scheduled_restart(plugin_name, now)
            if isinstance(restart_result, dict):
                results["scheduled_restarts"].append(restart_result)
                notifications = restart_result.get("notifications")
                if isinstance(notifications, list):
                    results["notifications"].extend([dict(item) for item in notifications if isinstance(item, dict)])
        return results

    def _current_datetime(self):
        return datetime.now().astimezone()

    @staticmethod
    def _parse_schedule_time(value):
        text = str(value or "").strip()
        if not text:
            return None
        parts = text.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            return None
        hour = int(parts[0])
        minute = int(parts[1])
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            return None
        return hour, minute

    def _scheduled_policy_for_plugin(self, plugin_name):
        if not self._cluster_root:
            return {}
        try:
            defaults = load_plugin_defaults(str(self._cluster_root), str(plugin_name))
        except Exception:
            return {}
        return {
            "scheduled_restart_enabled": bool(defaults.get("scheduled_restart_enabled")),
            "scheduled_restart_time": str(defaults.get("scheduled_restart_time") or "").strip(),
            "scheduled_update_check_enabled": bool(defaults.get("scheduled_update_check_enabled")),
            "scheduled_update_check_time": str(defaults.get("scheduled_update_check_time") or "").strip(),
            "scheduled_update_auto_apply": bool(defaults.get("scheduled_update_auto_apply")),
        }

    def _scheduled_policy_state_for_plugin(self, plugin_name):
        state = self._scheduled_policy_state.setdefault(str(plugin_name), {})
        return state if isinstance(state, dict) else {}

    def _save_scheduled_policy_state(self):
        save_scheduled_policy_state(self._cluster_root, self._scheduled_policy_state)

    def _next_scheduled_datetime_text(self, now, schedule_time_value, last_date_value):
        parsed = self._parse_schedule_time(schedule_time_value)
        if parsed is None:
            return ""
        hour, minute = parsed
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        today = now.date().isoformat()
        if candidate <= now or str(last_date_value or "").strip() == today:
            from datetime import timedelta
            candidate = candidate + timedelta(days=1)
        return candidate.isoformat()

    def get_plugin_schedule_status(self, plugin_name, current_datetime=None):
        now = current_datetime if isinstance(current_datetime, datetime) else self._current_datetime()
        policy = self._scheduled_policy_for_plugin(plugin_name)
        state = dict(self._scheduled_policy_state_for_plugin(plugin_name))
        return {
            "plugin_name": str(plugin_name),
            "scheduled_update_check_enabled": bool(policy.get("scheduled_update_check_enabled")),
            "scheduled_update_check_time": str(policy.get("scheduled_update_check_time") or ""),
            "scheduled_update_auto_apply": bool(policy.get("scheduled_update_auto_apply")),
            "next_scheduled_update_check_at": self._next_scheduled_datetime_text(
                now,
                policy.get("scheduled_update_check_time"),
                state.get("last_update_check_date"),
            ),
            "last_update_check_at": str(state.get("last_update_check_at") or ""),
            "last_update_check_result": str(state.get("last_update_check_result") or ""),
            "last_scheduled_apply_at": str(state.get("last_scheduled_apply_at") or ""),
            "last_scheduled_apply_result": str(state.get("last_scheduled_apply_result") or ""),
            "scheduled_restart_enabled": bool(policy.get("scheduled_restart_enabled")),
            "scheduled_restart_time": str(policy.get("scheduled_restart_time") or ""),
            "next_scheduled_restart_at": self._next_scheduled_datetime_text(
                now,
                policy.get("scheduled_restart_time"),
                state.get("last_restart_date"),
            ),
            "last_scheduled_restart_at": str(state.get("last_restart_at") or ""),
            "last_scheduled_restart_result": str(state.get("last_restart_result") or ""),
        }

    def _schedule_is_due_today(self, last_date_value, now, schedule_time_value):
        parsed = self._parse_schedule_time(schedule_time_value)
        if parsed is None:
            return False
        hour, minute = parsed
        today = now.date().isoformat()
        if str(last_date_value or "").strip() == today:
            return False
        return (int(now.hour), int(now.minute)) >= (int(hour), int(minute))

    def _iter_instance_ids(self, plugin_name):
        if not self._cluster_root:
            return []
        base = Path(str(self._cluster_root)) / "plugins" / str(plugin_name) / "instances"
        if not base.is_dir():
            return []
        out = []
        for path in sorted([item for item in base.iterdir() if item.is_dir()], key=lambda item: item.name):
            if (path / "instance.json").is_file():
                out.append(str(path.name))
        return out

    def _plugin_has_updates_available(self, plugin_update_resp):
        data = plugin_update_resp.get("data") if isinstance(plugin_update_resp, dict) else None
        if not isinstance(data, dict):
            return False
        instances = data.get("instances")
        if isinstance(instances, dict):
            for item in instances.values():
                if isinstance(item, dict) and bool(item.get("update_available")):
                    return True
        return False

    @staticmethod
    def _scheduled_notification(title, message, *, level="info"):
        return {
            "title": str(title or "").strip() or "Scheduled Task",
            "message": str(message or "").strip(),
            "level": str(level or "info").strip().lower() or "info",
        }

    def _instance_in_transitional_state(self, plugin_name, instance_id):
        state = str(self.get_instance_state(plugin_name, instance_id) or "").upper()
        return state in {"STARTING", "STOPPING", "RESTARTING", "INSTALLING", "SHUTTING DOWN"}

    def _run_scheduled_update_check(self, plugin_name, now):
        policy = self._scheduled_policy_for_plugin(plugin_name)
        if not bool(policy.get("scheduled_update_check_enabled")):
            return None
        state = self._scheduled_policy_state_for_plugin(plugin_name)
        if not self._schedule_is_due_today(state.get("last_update_check_date"), now, policy.get("scheduled_update_check_time")):
            return None
        state["last_update_check_date"] = now.date().isoformat()
        state["last_update_check_at"] = now.isoformat()
        response = self.check_plugin_update(plugin_name)
        has_updates = self._plugin_has_updates_available(response)
        result = {
            "plugin_name": str(plugin_name),
            "ran": True,
            "auto_apply": bool(policy.get("scheduled_update_auto_apply")),
            "status": str(response.get("status") or "error") if isinstance(response, dict) else "error",
            "outcome": "skipped",
            "notifications": [],
        }
        if str(result["status"]) != "success":
            state["last_update_check_result"] = "Failed: scheduled update check failed"
            result["outcome"] = "failed"
            self._save_scheduled_policy_state()
            return result

        if not has_updates:
            state["last_update_check_result"] = "Skipped: no updates available"
            self._save_scheduled_policy_state()
            return result

        if not bool(policy.get("scheduled_update_auto_apply")):
            state["last_update_check_result"] = "Skipped: updates available, waiting for manual apply"
            self._save_scheduled_policy_state()
            return result

        prepare_response = self.prepare_master_install(plugin_name)
        prepare_ok = self._resp_ok(prepare_response)
        prepare_data = prepare_response.get("data") if isinstance(prepare_response, dict) else None
        master_ready = bool((prepare_data or {}).get("master_install_ready") or (prepare_data or {}).get("ok"))
        apply_results = []
        skipped_instances = []
        if prepare_ok and master_ready:
            for instance_id in self._iter_instance_ids(plugin_name):
                if self.get_instance_disabled_state(plugin_name, instance_id):
                    skipped_instances.append({"instance_id": str(instance_id), "reason": "instance disabled"})
                    continue
                if self.get_instance_install_status(plugin_name, instance_id) != "INSTALLED":
                    skipped_instances.append({"instance_id": str(instance_id), "reason": "instance not installed"})
                    continue
                if self._instance_in_transitional_state(plugin_name, instance_id):
                    skipped_instances.append({"instance_id": str(instance_id), "reason": "instance in transitional state"})
                    continue
                if self._runtime_running(plugin_name, instance_id):
                    apply_results.append({"instance_id": str(instance_id), "response": self.update_instance(plugin_name, instance_id)})
                else:
                    apply_results.append({"instance_id": str(instance_id), "response": self.install_server_instance(plugin_name, instance_id)})
        result["prepare_master_status"] = str(prepare_response.get("status") or "error") if isinstance(prepare_response, dict) else "error"
        result["apply_results"] = apply_results
        result["skipped_instances"] = skipped_instances
        applied_count = len(apply_results)
        success_count = sum(
            1
            for item in apply_results
            if isinstance(item, dict)
            and isinstance(item.get("response"), dict)
            and str(item["response"].get("status") or "") == "success"
        )
        if not prepare_ok or not master_ready:
            detail = str((prepare_response.get("message") if isinstance(prepare_response, dict) else "") or "master prepare failed").strip()
            state["last_update_check_result"] = "Updates available"
            state["last_scheduled_apply_at"] = now.isoformat()
            state["last_scheduled_apply_result"] = f"Failed: updates available, apply blocked ({detail})"
            result["outcome"] = "failed"
            result["notifications"].append(
                self._scheduled_notification(
                    "Scheduled Update Apply Blocked",
                    f"{plugin_name}: updates are available but scheduled apply was blocked. {detail}",
                    level="error",
                )
            )
            self._save_scheduled_policy_state()
            return result
        state["last_update_check_result"] = "Updates available"
        state["last_scheduled_apply_at"] = now.isoformat()
        if applied_count == 0:
            state["last_scheduled_apply_result"] = "Skipped: no eligible instances"
            result["outcome"] = "skipped"
        elif success_count == applied_count:
            state["last_scheduled_apply_result"] = f"Applied: {success_count}/{applied_count} instance updates"
            result["outcome"] = "applied"
        else:
            state["last_scheduled_apply_result"] = f"Failed: applied {success_count}/{applied_count} instance updates"
            result["outcome"] = "failed"
            result["notifications"].append(
                self._scheduled_notification(
                    "Scheduled Update Apply Failed",
                    f"{plugin_name}: scheduled apply completed only {success_count}/{applied_count} instance updates.",
                    level="error",
                )
            )
        self._save_scheduled_policy_state()
        return result

    def _run_scheduled_restart(self, plugin_name, now):
        policy = self._scheduled_policy_for_plugin(plugin_name)
        if not bool(policy.get("scheduled_restart_enabled")):
            return None
        state = self._scheduled_policy_state_for_plugin(plugin_name)
        if not self._schedule_is_due_today(state.get("last_restart_date"), now, policy.get("scheduled_restart_time")):
            return None
        state["last_restart_date"] = now.date().isoformat()
        state["last_restart_at"] = now.isoformat()
        results = []
        skipped_instances = []
        for instance_id in self._iter_instance_ids(plugin_name):
            if self.get_instance_disabled_state(plugin_name, instance_id):
                skipped_instances.append({"instance_id": str(instance_id), "reason": "instance disabled"})
                continue
            if not self._runtime_running(plugin_name, instance_id):
                skipped_instances.append({"instance_id": str(instance_id), "reason": "instance not running"})
                continue
            if self._instance_in_transitional_state(plugin_name, instance_id):
                skipped_instances.append({"instance_id": str(instance_id), "reason": "instance already restarting or transitioning"})
                continue
            results.append({"instance_id": str(instance_id), "response": self.restart_instance(plugin_name, instance_id, restart_reason="scheduled")})
        success_count = sum(
            1
            for item in results
            if isinstance(item, dict)
            and isinstance(item.get("response"), dict)
            and str(item["response"].get("status") or "") == "success"
        )
        if not results:
            state["last_restart_result"] = "Skipped: no eligible running instances"
            outcome = "skipped"
        elif success_count == len(results):
            state["last_restart_result"] = f"Applied: restarted {success_count}/{len(results)} running instances"
            outcome = "applied"
        else:
            state["last_restart_result"] = f"Failed: restarted {success_count}/{len(results)} running instances"
            outcome = "failed"
        self._save_scheduled_policy_state()
        out = {
            "plugin_name": str(plugin_name),
            "ran": True,
            "results": results,
            "skipped_instances": skipped_instances,
            "outcome": outcome,
            "notifications": [],
        }
        if outcome == "failed":
            out["notifications"].append(
                self._scheduled_notification(
                    "Scheduled Restart Failed",
                    f"{plugin_name}: scheduled restart completed only {success_count}/{len(results)} running instances.",
                    level="error",
                )
            )
        return out

    ############################################################
    # SECTION: Lifecycle Inspection API (Read-Only)
    # Purpose:
    #     Expose authoritative lifecycle state for read-only checks.
    # Constraints:
    #     - No transitions
    #     - No scheduler interaction
    #     - No side effects
    ############################################################
    def get_instance_state(self, plugin_name, instance_id):
        self._state_manager.ensure_instance_exists(plugin_name, instance_id)
        return self._state_manager.get_state(plugin_name, instance_id)

    def set_instance_last_action(self, plugin_name, instance_id, action):
        self._instance_last_action[(str(plugin_name), str(instance_id))] = str(action)

    def get_instance_last_action(self, plugin_name, instance_id):
        return self._instance_last_action.get((str(plugin_name), str(instance_id)))

    def _now(self) -> float:
        return float(time.monotonic())

    def _set_stop_deadline(self, plugin_name, instance_id):
        key = (str(plugin_name), str(instance_id))
        self._stop_deadlines[key] = self._now() + float(_STOPPING_FORCE_TIMEOUT_SECONDS)

    def _clear_stop_deadline(self, plugin_name, instance_id):
        key = (str(plugin_name), str(instance_id))
        self._stop_deadlines.pop(key, None)

    def _runtime_running(self, plugin_name, instance_id) -> bool:
        runtime_response = self.send_action(
            plugin_name,
            "runtime_summary",
            {"instance_id": str(instance_id)}
        )
        if isinstance(runtime_response, dict) and runtime_response.get("status") == "success":
            runtime_data = runtime_response.get("data")
            if isinstance(runtime_data, dict):
                return bool(runtime_data.get("running"))
        return False

    def _runtime_summary_key(self, plugin_name, instance_id):
        return str(plugin_name), str(instance_id)

    def read_cached_runtime_summary(self, plugin_name, instance_id):
        # Cached read only. Callers that need fresh runtime truth must go
        # through refresh_runtime_summary().
        key = self._runtime_summary_key(plugin_name, instance_id)
        cached = self._cached_runtime_summaries.get(key)
        if isinstance(cached, dict):
            return dict(cached)
        return {
            "status": "success",
            "data": {
                "ok": True,
                "display_name": "",
                "running": False,
                "ready": False,
                "pid": None,
                "pid_file_present": False,
                "pid_from_file": None,
                "process_probe_running": False,
                "version": {"installed": None, "running": None},
                "warnings": [],
                "errors": [],
            },
        }

    def refresh_runtime_summary(self, plugin_name, instance_id):
        # Lightweight runtime poll only. Freshness guard prevents timer/manual
        # entrypoints from duplicating the same work in a hot loop.
        key = self._runtime_summary_key(plugin_name, instance_id)
        cached = self._cached_runtime_summaries.get(key)
        last_updated = float(self._runtime_summary_last_updated.get(key, 0.0) or 0.0)
        now = self._now()
        if key in self._runtime_summary_inflight and isinstance(cached, dict):
            return dict(cached)
        if isinstance(cached, dict) and (now - last_updated) < float(_RUNTIME_SUMMARY_MIN_REFRESH_SECONDS):
            return dict(cached)

        self._runtime_summary_inflight.add(key)
        try:
            resp = self.send_action(
                str(plugin_name),
                "runtime_summary",
                {"instance_id": str(instance_id)},
            )
            self._cached_runtime_summaries[key] = dict(resp) if isinstance(resp, dict) else {
                "status": "error",
                "message": "runtime_summary failed",
            }
            if isinstance(self._cached_runtime_summaries[key], dict):
                evaluated = self._evaluate_pending_update_verification(
                    plugin_name,
                    instance_id,
                    self._cached_runtime_summaries[key],
                )
                if isinstance(evaluated, dict) and evaluated.get("ok") is False:
                    self._cached_runtime_summaries[key] = self._attach_update_verification_notification(
                        plugin_name,
                        instance_id,
                        self._cached_runtime_summaries[key],
                    )
            self._runtime_summary_last_updated[key] = now
        finally:
            self._runtime_summary_inflight.discard(key)
        return self.read_cached_runtime_summary(plugin_name, instance_id)

    def _refresh_runtime_summary_after_start(self, plugin_name, instance_id):
        key = self._runtime_summary_key(plugin_name, instance_id)
        resp = self.send_action(
            str(plugin_name),
            "runtime_summary",
            {"instance_id": str(instance_id)},
        )
        self._cached_runtime_summaries[key] = dict(resp) if isinstance(resp, dict) else {
            "status": "error",
            "message": "runtime_summary failed",
        }
        if isinstance(self._cached_runtime_summaries[key], dict):
            evaluated = self._evaluate_pending_update_verification(
                plugin_name,
                instance_id,
                self._cached_runtime_summaries[key],
            )
            if isinstance(evaluated, dict) and evaluated.get("ok") is False:
                self._cached_runtime_summaries[key] = self._attach_update_verification_notification(
                    plugin_name,
                    instance_id,
                    self._cached_runtime_summaries[key],
                )
        self._runtime_summary_last_updated[key] = self._now()
        return self.read_cached_runtime_summary(plugin_name, instance_id)

    @staticmethod
    def _version_tuple(value):
        text = str(value or "").strip()
        if not text:
            return None
        parts = []
        for token in text.split("."):
            token = token.strip()
            if not token.isdigit():
                return None
            parts.append(int(token))
        return tuple(parts) if parts else None

    def _best_known_version(self, summary):
        data = summary.get("data") if isinstance(summary, dict) else None
        version = data.get("version") if isinstance(data, dict) else None
        if not isinstance(version, dict):
            return None
        candidates = []
        for key in ("running", "installed"):
            raw = version.get(key)
            parsed = self._version_tuple(raw)
            if parsed is not None:
                candidates.append((parsed, str(raw)))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[-1][1]

    def _current_version_for_update_compare(self, plugin_name, instance_id):
        summary = self.read_cached_runtime_summary(plugin_name, instance_id)
        current_version = self._best_known_version(summary)
        if current_version:
            return str(current_version)
        key = self._runtime_summary_key(plugin_name, instance_id)
        self._runtime_summary_last_updated[key] = 0.0
        refreshed = self.refresh_runtime_summary(plugin_name, instance_id)
        refreshed_version = self._best_known_version(refreshed)
        if refreshed_version:
            return str(refreshed_version)
        return "unknown"

    @staticmethod
    def _runtime_summary_running_state(summary):
        data = summary.get("data") if isinstance(summary, dict) else None
        if not isinstance(data, dict):
            return None
        running = data.get("running")
        if running is True:
            return True
        if running is False:
            return False
        return None

    @staticmethod
    def _build_id_text(value):
        text = str(value or "").strip()
        return text if text.isdigit() and text != "0" else None

    def _current_build_for_update_compare(self, plugin_name, instance_id):
        layout = self._resolve_instance_install_layout(plugin_name, instance_id)
        logs_dir = str((layout or {}).get("logs_dir") or "").strip()
        if not logs_dir:
            return None
        check_update_log = Path(logs_dir) / "check_update.log"
        if not check_update_log.is_file():
            return None
        try:
            from core.steam_installer import extract_steamcmd_appstate_build_ids

            current_build_id, _target_build_id = extract_steamcmd_appstate_build_ids(
                check_update_log.read_text(encoding="utf-8", errors="replace")
            )
        except Exception:
            return None
        return self._build_id_text(current_build_id)

    def _version_build_map_path(self):
        cluster_fields = self._load_cluster_config_fields() or {}
        return resolve_version_build_map_path(
            cluster_root=str(self._cluster_root or ""),
            gameservers_root=str(cluster_fields.get("gameservers_root") or ""),
        )

    def _load_version_build_map(self):
        plugins = load_version_build_plugins_state(self._version_build_map_path())
        if not isinstance(plugins, dict) or not plugins:
            self._version_build_map = {}
            self._version_build_state = {}
            return {}
        out = {}
        state = {}
        for plugin_name, items in plugins.items():
            if not isinstance(items, dict):
                continue
            raw_builds = items.get("builds") if isinstance(items.get("builds"), dict) else items
            normalized = {}
            for build_id, version in raw_builds.items():
                build_text = str(build_id or "").strip()
                version_text = str(version or "").strip()
                if build_text and version_text:
                    normalized[build_text] = version_text
            if normalized:
                out[str(plugin_name)] = normalized
            master_current_build_id = self._build_id_text(items.get("master_current_build_id"))
            if master_current_build_id:
                state[str(plugin_name)] = {"master_current_build_id": master_current_build_id}
        self._version_build_map = out
        self._version_build_state = state
        return out

    def _mapped_version_for_build(self, plugin_name, build_id):
        plugin_map = self._version_build_map.get(str(plugin_name or "").strip(), {})
        if not isinstance(plugin_map, dict):
            return None
        value = plugin_map.get(str(build_id or "").strip())
        text = str(value or "").strip()
        return text or None

    def _stored_master_build_for_plugin(self, plugin_name):
        state = self._version_build_state.get(str(plugin_name or "").strip(), {})
        if not isinstance(state, dict):
            return None
        return self._build_id_text(state.get("master_current_build_id"))

    def _resolved_master_update_fields(self, plugin_name, data):
        if not isinstance(data, dict):
            return {
                "master_current_version": None,
                "master_current_build_id": None,
                "target_version": None,
                "master_install_ready": False,
            }
        master_current_version = str(data.get("master_current_version") or "").strip() or None
        master_current_build_id = (
            self._build_id_text(data.get("current_build_id"))
            or self._stored_master_build_for_plugin(plugin_name)
        )
        target_version = self._build_id_text(data.get("target_version"))
        if master_current_build_id and not master_current_version:
            master_current_version = self._mapped_version_for_build(plugin_name, master_current_build_id)
        if target_version and not master_current_version:
            master_current_version = self._mapped_version_for_build(plugin_name, target_version)
        return {
            "master_current_version": master_current_version,
            "master_current_build_id": master_current_build_id,
            "target_version": target_version,
            "master_install_ready": bool(str(data.get("install_root") or "").strip()),
        }

    def _instance_update_compare_fields(self, plugin_name, instance_id, *, master_current_version, target_version):
        current_version = self._current_version_for_update_compare(plugin_name, instance_id)
        current_build_id = self._current_build_for_update_compare(plugin_name, instance_id)
        update_available = False
        if current_build_id and target_version:
            update_available = int(target_version) > int(current_build_id)
        elif master_current_version and self._versions_are_comparable(current_version, master_current_version):
            current_tuple = self._version_tuple(current_version)
            target_tuple = self._version_tuple(master_current_version)
            update_available = bool(
                current_tuple is not None
                and target_tuple is not None
                and target_tuple > current_tuple
            )
        return {
            "current_version": current_version,
            "current_build_id": current_build_id,
            "update_available": update_available,
        }

    def _save_version_build_map(self):
        plugins = {}
        for plugin_name in sorted(set(self._version_build_map) | set(self._version_build_state)):
            entry = {}
            master_current_build_id = self._stored_master_build_for_plugin(plugin_name)
            if master_current_build_id:
                entry["master_current_build_id"] = master_current_build_id
            builds = self._version_build_map.get(str(plugin_name), {})
            if isinstance(builds, dict) and builds:
                entry["builds"] = dict(sorted(((str(k), str(v)) for k, v in builds.items()), key=lambda item: item[0]))
            if entry:
                plugins[str(plugin_name)] = entry
        save_version_build_plugins_state(self._version_build_map_path(), plugins)

    def _persist_verified_build_version_mapping(self, plugin_name, build_id, version_text):
        plugin_text = str(plugin_name or "").strip()
        build_text = self._build_id_text(build_id)
        version_value = str(version_text or "").strip()
        if not plugin_text or not build_text or not version_value:
            return
        plugin_map = self._version_build_map.setdefault(plugin_text, {})
        if str(plugin_map.get(build_text) or "").strip() == version_value:
            return
        plugin_map[build_text] = version_value
        state = self._version_build_state.setdefault(plugin_text, {})
        state["master_current_build_id"] = build_text
        self._save_version_build_map()

    def _clear_update_verification_state(self, plugin_name, instance_id):
        key = (str(plugin_name), str(instance_id))
        self._pending_update_verifications.pop(key, None)

    def _begin_update_verification(self, plugin_name, instance_id, *, previous_version, expected_build_id, master_install_root="", install_root=""):
        build_text = self._build_id_text(expected_build_id)
        previous_text = str(previous_version or "").strip()
        if not build_text or not previous_text:
            return
        key = (str(plugin_name), str(instance_id))
        self._pending_update_verifications[key] = {
            "plugin_name": str(plugin_name),
            "instance_id": str(instance_id),
            "previous_version": previous_text,
            "expected_build_id": build_text,
            "master_install_root": str(master_install_root or "").strip(),
            "install_root": str(install_root or "").strip(),
        }
        self._pending_update_verification_notifications.pop(key, None)

    def _evaluate_pending_update_verification(self, plugin_name, instance_id, current_summary):
        key = (str(plugin_name), str(instance_id))
        pending = self._pending_update_verifications.get(key)
        if not isinstance(pending, dict):
            return None
        observed_version = str(self._best_known_version(current_summary) or "").strip()
        previous_version = str(pending.get("previous_version") or "").strip()
        observed_tuple = self._version_tuple(observed_version)
        previous_tuple = self._version_tuple(previous_version)
        if observed_tuple is None or previous_tuple is None:
            return None
        self._pending_update_verifications.pop(key, None)
        if observed_tuple <= previous_tuple:
            failure = {
                "plugin_name": str(plugin_name),
                "instance_id": str(instance_id),
                "expected_build_id": str(pending.get("expected_build_id") or "").strip(),
                "previous_version": previous_version,
                "observed_version": observed_version,
                "master_install_root": str(pending.get("master_install_root") or "").strip(),
                "install_root": str(pending.get("install_root") or "").strip(),
                "message": (
                    f"Update verification failed for {plugin_name} {instance_id}: "
                    f"expected build {str(pending.get('expected_build_id') or '').strip()}, "
                    f"previous version {previous_version}, observed version {observed_version}. "
                    f"Check the prepared master and Robocopy distribution."
                ),
            }
            self._pending_update_verification_notifications[key] = dict(failure)
            return {"ok": False, **failure}
        self._persist_verified_build_version_mapping(
            plugin_name,
            str(pending.get("expected_build_id") or "").strip(),
            observed_version,
        )
        return {
            "ok": True,
            "expected_build_id": str(pending.get("expected_build_id") or "").strip(),
            "observed_version": observed_version,
        }

    def _attach_update_verification_notification(self, plugin_name, instance_id, response):
        key = (str(plugin_name), str(instance_id))
        failure = self._pending_update_verification_notifications.pop(key, None)
        if not isinstance(failure, dict) or not isinstance(response, dict):
            return response
        data = response.get("data")
        if not isinstance(data, dict):
            data = {}
            response["data"] = data
        data["update_verification_failure"] = dict(failure)
        return response

    def _highest_known_plugin_version(self, plugin_name, exclude_instance_id=None):
        plugin_name_s = str(plugin_name)
        exclude_instance = str(exclude_instance_id) if exclude_instance_id is not None else None
        candidates = []
        for key, summary in dict(self._cached_runtime_summaries or {}).items():
            if not isinstance(key, tuple) or len(key) != 2:
                continue
            cached_plugin, cached_instance = key
            if str(cached_plugin) != plugin_name_s:
                continue
            if exclude_instance is not None and str(cached_instance) == exclude_instance:
                continue
            version = self._best_known_version(summary)
            parsed = self._version_tuple(version)
            if parsed is None:
                continue
            candidates.append((parsed, str(version)))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[-1][1]

    def _build_started_version_notice(self, plugin_name, instance_id, previous_summary, current_summary):
        previous = self._best_known_version(previous_summary)
        current = self._best_known_version(current_summary)
        if not previous or not current:
            return None
        previous_tuple = self._version_tuple(previous)
        current_tuple = self._version_tuple(current)
        if previous_tuple is None or current_tuple is None or current_tuple <= previous_tuple:
            return None
        self._emit_event(
            EVENT_INSTANCE_VERSION_ADVANCED,
            plugin_name,
            instance_id,
            payload={"previous_version": previous, "current_version": current},
        )
        return f"Version notice: server reported newer version {current} (was {previous})."

    @staticmethod
    def _versions_are_comparable(current_version, target_version) -> bool:
        current = str(current_version or "").strip()
        target = str(target_version or "").strip()
        if not current or not target:
            return False
        current_tuple = Orchestrator._version_tuple(current)
        target_tuple = Orchestrator._version_tuple(target)
        if current_tuple is None or target_tuple is None:
            return False
        return ("." in current) == ("." in target)

    def inspect_runtime_status(self, plugin_name, instance_id):
        # Explicit deep runtime inspection surface. This is intentionally kept
        # separate from runtime summary so UI refresh paths cannot reach it by
        # accident.
        key = self._runtime_summary_key(plugin_name, instance_id)
        cached = self._cached_runtime_inspects.get(key)
        last_updated = float(self._runtime_inspect_last_updated.get(key, 0.0) or 0.0)
        now = self._now()
        if key in self._runtime_inspect_inflight and isinstance(cached, dict):
            return dict(cached)
        if isinstance(cached, dict) and (now - last_updated) < float(_DEEP_RUNTIME_INSPECT_MIN_REFRESH_SECONDS):
            return dict(cached)

        self._runtime_inspect_inflight.add(key)
        try:
            resp = self.send_action(
                str(plugin_name),
                "runtime_status",
                {"instance_id": str(instance_id)},
            )
            self._cached_runtime_inspects[key] = dict(resp) if isinstance(resp, dict) else {
                "status": "error",
                "message": "runtime_status failed",
            }
            self._runtime_inspect_last_updated[key] = now
        finally:
            self._runtime_inspect_inflight.discard(key)
        return dict(self._cached_runtime_inspects.get(key) or {"status": "error", "message": "runtime_status failed"})

    def reconcile_stop_progress(self, plugin_name, instance_id):
        self._state_manager.ensure_instance_exists(plugin_name, instance_id)
        current_state = self._state_manager.get_state(plugin_name, instance_id)
        if current_state != self._state_manager.STOPPING:
            return {"status": "noop", "forced": False, "runtime_running": None}

        runtime_running = self._runtime_running(plugin_name, instance_id)
        if not runtime_running:
            self._state_manager.set_state(plugin_name, instance_id, self._state_manager.STOPPED)
            self._clear_stop_deadline(plugin_name, instance_id)
            self._emit_event(EVENT_INSTANCE_STOPPED, plugin_name, instance_id)
            return {"status": "stopped", "forced": False, "runtime_running": False}

        key = (str(plugin_name), str(instance_id))
        deadline = self._stop_deadlines.get(key)
        if deadline is None:
            self._set_stop_deadline(plugin_name, instance_id)
            return {"status": "stopping", "forced": False, "runtime_running": True}

        if self._now() < float(deadline):
            return {"status": "stopping", "forced": False, "runtime_running": True}

        force_response = self.send_action(
            plugin_name,
            "stop",
            {"instance_id": instance_id}
        )

        force_ok = isinstance(force_response, dict) and force_response.get("status") == "success"
        runtime_running_after = self._runtime_running(plugin_name, instance_id) if force_ok else True

        if force_ok and not runtime_running_after:
            self._state_manager.set_state(plugin_name, instance_id, self._state_manager.STOPPED)
            self._clear_stop_deadline(plugin_name, instance_id)
            self._emit_event(EVENT_INSTANCE_STOPPED, plugin_name, instance_id)
            return {"status": "stopped", "forced": True, "runtime_running": False}

        return {"status": "stopping", "forced": force_ok, "runtime_running": True}



    ############################################################
    # SECTION: Crash Counter Internal Access
    # Purpose:
    # Ensure per-instance counter structure exists.
    # Lifecycle Ownership:
    # Orchestrator (Core)
    # Phase:
    # Crash Architecture - Phase 2 (Dual Counters)
    # Constraints:
    # - Memory only.
    # - No threshold logic.
    # - No disable logic.
    ############################################################
    def _ensure_counter_entry(self, plugin_name, instance_id):
        key = (plugin_name, instance_id)
        if key not in self._crash_counters:
            self._crash_counters[key] = {
                "crash_total_count": 0,
                "crash_stability_count": 0
            }
        return key

    ############################################################
    # SECTION: Crash Counter Inspection API
    # Purpose:
    # Provide read-only access to crash counters.
    # Lifecycle Ownership:
    # Orchestrator (Core)
    # Phase:
    # Crash Architecture - Phase 2 (Dual Counters)
    # Constraints:
    # - Memory only.
    # - No threshold logic.
    # - No disable logic.
    ############################################################
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

    ############################################################
    # SECTION: Crash Total Counter Manual Reset API
    # Purpose:
    # Explicitly reset crash_total_count.
    # Lifecycle Ownership:
    # Orchestrator (Core)
    # Phase:
    # Crash Architecture - Phase 2 (Dual Counters)
    # Constraints:
    # - Memory only.
    # - No threshold logic.
    # - No disable logic.
    ############################################################
    def reset_crash_total_count(self, plugin_name, instance_id):
        key = self._ensure_counter_entry(plugin_name, instance_id)
        self._crash_counters[key]["crash_total_count"] = 0

    ############################################################
    # SECTION: Threshold Management
    # Purpose:
    # Manage global and per-instance thresholds.
    # Lifecycle Ownership:
    # Orchestrator (Core)
    # Phase:
    # Crash Architecture - Phase 3 (Threshold Enforcement)
    # Constraints:
    # - No persistence.
    # - No time windows.
    # - No backoff logic.
    ############################################################
    def set_global_threshold(self, value):
        self._global_threshold = int(value)

    def set_plugin_threshold(self, plugin_name, value):
        self._plugin_thresholds[plugin_name] = int(value)

    def set_instance_threshold(self, plugin_name, instance_id, value):
        key = (plugin_name, instance_id)
        self._instance_thresholds[key] = int(value)

    def get_effective_threshold(self, plugin_name, instance_id):
        key = (plugin_name, instance_id)
        if key in self._instance_thresholds:
            return self._instance_thresholds[key]
        if plugin_name in self._plugin_thresholds:
            return self._plugin_thresholds[plugin_name]
        return self._global_threshold

    ############################################################
    # SECTION: Disabled State Inspection API
    # Purpose:
    # Provide read-only disabled state access.
    # Lifecycle Ownership:
    # Orchestrator (Core)
    # Phase:
    # Crash Architecture - Phase 3 (Threshold Enforcement)
    # Constraints:
    # - No persistence.
    # - No time windows.
    # - No backoff logic.
    ############################################################
    def get_instance_disabled_state(self, plugin_name, instance_id):
        return self._state_manager.get_state(plugin_name, instance_id) == self._state_manager.DISABLED

    def get_instance_install_status(self, plugin_name, instance_id):
        """
        Read-only visibility.

        Deterministic rules:
        - If cluster_root not configured: NOT_INSTALLED
        - If instance.json missing or key missing: NOT_INSTALLED
        - No timestamps
        - No side effects
        """
        if not self._cluster_root:
            return "NOT_INSTALLED"

        from core.instance_layout import read_instance_install_status
        return read_instance_install_status(self._cluster_root, plugin_name, instance_id)
    ############################################################
    # SECTION: Plugin Management
    ############################################################
    def load_plugins(self):
        self._registry.load_all()
        self._mark_plugin_readiness_dirty()

    def list_plugins(self):
        return self._registry.list_all()

    def _load_cluster_config_fields(self):
        from pathlib import Path
        from core.config_io import load_cluster_config

        if not self._cluster_root:
            return {}

        root = Path(str(self._cluster_root))
        candidates = [
            root / "cluster_config.json",
            root / "config" / "cluster_config.json",
        ]
        for path in candidates:
            if not path.exists() or not path.is_file():
                continue
            try:
                cfg = load_cluster_config(path)
            except Exception:
                continue
            return {
                "gameservers_root": str(getattr(cfg, "gameservers_root", "") or ""),
                "cluster_name": str(getattr(cfg, "cluster_name", "") or ""),
                "steamcmd_root": str(getattr(cfg, "steamcmd_root", "") or ""),
            }

    def _resolve_effective_steamcmd_root(self, raw_root):
        value = str(raw_root or "").strip()
        if not value:
            return ""
        if os.path.isabs(value) or not self._cluster_root:
            return os.path.abspath(value)
        return os.path.abspath(os.path.join(str(self._cluster_root), value))
        return {}

    def _evaluate_declared_dependency(self, plugin_name, dependency, defaults):
        from pathlib import Path

        if not isinstance(dependency, dict):
            label = str(dependency).strip() or "dependency"
            return {"id": label, "label": label, "status": "missing", "details": "Invalid dependency declaration."}

        dep_id = str(dependency.get("id") or dependency.get("field") or dependency.get("label") or "dependency").strip()
        label = str(dependency.get("label") or dep_id).strip() or dep_id
        dep_type = str(dependency.get("type") or "config_path").strip().lower()
        field = str(dependency.get("field") or "").strip()
        expected = str(dependency.get("expected") or "file").strip().lower()
        raw_guidance = dependency.get("guidance")
        if isinstance(raw_guidance, str):
            guidance = {"message": raw_guidance}
        elif isinstance(raw_guidance, dict):
            guidance = raw_guidance
        else:
            guidance = None

        # platforms filtering: skip dependency if not applicable on current OS.
        # "windows_server" is never matched (can't detect server edition cheaply).
        platforms = dependency.get("platforms")
        if platforms:
            is_windows = os.name == "nt"
            applicable = any(str(p).lower() == "windows" and is_windows for p in platforms)
            if not applicable:
                return {"id": dep_id, "label": label, "status": "installed", "details": "Not applicable on this platform."}

        if dep_type == "windows_component":
            component_id = field or dep_id
            return self._evaluate_windows_component_dependency(dep_id, label, component_id, guidance)

        if dep_type == "windows_certificate":
            return {"id": dep_id, "label": label, "status": "installed", "details": "Certificate dependency; manual verification only.", "guidance": guidance}

        if not field:
            return {"id": dep_id, "label": label, "status": "missing", "details": "Unsupported dependency declaration."}

        source = defaults
        if dep_type == "app_config_path":
            source = {}
            try:
                source["steamcmd_root"] = self._resolve_effective_steamcmd_root(
                    self._load_cluster_config_fields().get("steamcmd_root")
                )
            except Exception:
                source["steamcmd_root"] = ""
        elif dep_type != "config_path":
            return {"id": dep_id, "label": label, "status": "missing", "details": "Unsupported dependency declaration."}

        raw_value = source.get(field)
        value = str(raw_value or "").strip()
        if not value:
            return {"id": dep_id, "label": label, "status": "missing", "details": f"{field} is not configured.", "guidance": guidance}

        path = Path(value).expanduser()
        install_action = str((guidance or {}).get("action") or "").strip().lower()
        if dep_type == "app_config_path" and install_action == "install_steamcmd":
            exe_path = path / "steamcmd.exe"
            if exe_path.is_file():
                return {"id": dep_id, "label": label, "status": "installed", "details": str(exe_path), "guidance": guidance}
            failed_state = self._read_app_dependency_state(dep_id)
            if failed_state:
                return {"id": dep_id, "label": label, "status": "install_failed", "details": str(failed_state), "guidance": guidance}
            return {"id": dep_id, "label": label, "status": "install_available", "details": str(path), "guidance": guidance}

        exists = path.exists()
        if expected == "dir":
            ok = exists and path.is_dir()
        elif expected == "file":
            ok = exists and path.is_file()
        else:
            ok = exists
        if ok:
            return {"id": dep_id, "label": label, "status": "installed", "details": str(path), "guidance": guidance}
        return {"id": dep_id, "label": label, "status": "missing", "details": str(path), "guidance": guidance}

    def _check_windows_component(self, component_id):
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

    def _evaluate_windows_component_dependency(self, dep_id, label, component_id, guidance):
        message = str((guidance or {}).get("message") or "").strip()
        if os.name != "nt":
            details = message or "Windows-only dependency check."
            return {"id": dep_id, "label": label, "status": "missing", "details": details, "guidance": guidance}

        ok, detail = self._check_windows_component(component_id)
        if ok:
            return {"id": dep_id, "label": label, "status": "installed", "details": str(detail or component_id), "guidance": guidance}

        details = message or str(detail or component_id)
        return {"id": dep_id, "label": label, "status": "missing", "details": details, "guidance": guidance}

    def _app_dependency_state_path(self):
        from pathlib import Path

        if not self._cluster_root:
            return None
        return Path(str(self._cluster_root)) / "state" / "app_dependency_state.json"

    def _load_app_dependency_state_map(self):
        path = self._app_dependency_state_path()
        if path is None or not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_app_dependency_state_map(self, payload):
        path = self._app_dependency_state_path()
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _read_app_dependency_state(self, dep_id):
        payload = self._load_app_dependency_state_map()
        item = payload.get(str(dep_id))
        if not isinstance(item, dict):
            return ""
        if str(item.get("status") or "").strip().lower() != "install_failed":
            return ""
        return str(item.get("details") or "").strip()

    def _set_app_dependency_failed(self, dep_id, details):
        payload = self._load_app_dependency_state_map()
        payload[str(dep_id)] = {
            "status": "install_failed",
            "details": str(details or "").strip(),
        }
        self._write_app_dependency_state_map(payload)
        self._mark_app_setup_report_dirty()
        for plugin_name in self._plugins_for_dependency(dep_id):
            self._mark_plugin_readiness_dirty(plugin_name)
            self._invalidate_runtime_summary(plugin_name)
            for affected_plugin, instance_id in self._iter_instance_keys(plugin_name):
                self._mark_instance_readiness_dirty(affected_plugin, instance_id)

    def _clear_app_dependency_state(self, dep_id):
        payload = self._load_app_dependency_state_map()
        if str(dep_id) in payload:
            payload.pop(str(dep_id), None)
            self._write_app_dependency_state_map(payload)
        self._mark_app_setup_report_dirty()
        for plugin_name in self._plugins_for_dependency(dep_id):
            self._mark_plugin_readiness_dirty(plugin_name)
            self._invalidate_runtime_summary(plugin_name)
            for affected_plugin, instance_id in self._iter_instance_keys(plugin_name):
                self._mark_instance_readiness_dirty(affected_plugin, instance_id)

    def _mark_app_setup_report_dirty(self):
        self._app_setup_dirty = True

    def _iter_instance_keys(self, plugin_name=None):
        from pathlib import Path

        if not self._cluster_root:
            return []

        plugins = [str(plugin_name)] if plugin_name is not None else [str(name) for name in list(self.list_plugins() or [])]
        root = Path(str(self._cluster_root)) / "plugins"
        out = []
        for plugin in plugins:
            base = root / str(plugin) / "instances"
            if not base.exists() or not base.is_dir():
                continue
            for entry in base.iterdir():
                if not entry.is_dir():
                    continue
                meta = entry / "instance.json"
                if meta.exists() and meta.is_file():
                    out.append((str(plugin), str(entry.name)))
        return out

    def _instance_readiness_key(self, plugin_name, instance_id):
        return (str(plugin_name), str(instance_id))

    def _mark_instance_readiness_dirty(self, plugin_name=None, instance_id=None):
        if plugin_name is None:
            self._instance_readiness_dirty_all = True
            self._dirty_instance_readiness.clear()
            self._dirty_instance_readiness_plugins.clear()
            return
        if instance_id is None:
            self._dirty_instance_readiness_plugins.add(str(plugin_name))
            return
        self._dirty_instance_readiness.add(self._instance_readiness_key(plugin_name, instance_id))

    def _mark_plugin_readiness_dirty(self, plugin_name=None):
        if plugin_name is None:
            self._plugin_readiness_dirty_all = True
            self._dirty_plugin_readiness.clear()
            return
        self._dirty_plugin_readiness.add(str(plugin_name))

    def _plugins_for_dependency(self, dep_id):
        dep_key = str(dep_id or "").strip().lower()
        registry = getattr(self, "_registry", None)
        if registry is None or not hasattr(registry, "get_metadata"):
            return []
        matches = []
        for plugin_name in list(self.list_plugins() or []):
            metadata = registry.get_metadata(str(plugin_name))
            dependencies = metadata.get("dependencies") if isinstance(metadata, dict) else []
            if not isinstance(dependencies, list):
                continue
            for item in dependencies:
                if isinstance(item, dict) and str(item.get("id") or "").strip().lower() == dep_key:
                    matches.append(str(plugin_name))
                    break
        return matches

    def _invalidate_runtime_summary(self, plugin_name=None, instance_id=None):
        if plugin_name is None:
            self._cached_runtime_summaries.clear()
            self._runtime_summary_last_updated.clear()
            self._runtime_summary_inflight.clear()
            self._cached_runtime_inspects.clear()
            self._runtime_inspect_last_updated.clear()
            self._runtime_inspect_inflight.clear()
            return
        if instance_id is None:
            for key in [k for k in self._cached_runtime_summaries.keys() if k[0] == str(plugin_name)]:
                self._cached_runtime_summaries.pop(key, None)
                self._runtime_summary_last_updated.pop(key, None)
                self._runtime_summary_inflight.discard(key)
                self._cached_runtime_inspects.pop(key, None)
                self._runtime_inspect_last_updated.pop(key, None)
                self._runtime_inspect_inflight.discard(key)
            return
        key = self._runtime_summary_key(plugin_name, instance_id)
        self._cached_runtime_summaries.pop(key, None)
        self._runtime_summary_last_updated.pop(key, None)
        self._runtime_summary_inflight.discard(key)
        self._cached_runtime_inspects.pop(key, None)
        self._runtime_inspect_last_updated.pop(key, None)
        self._runtime_inspect_inflight.discard(key)

    def _recompute_app_setup_report(self):
        cluster_fields = self._load_cluster_config_fields()
        cluster_fields = cluster_fields or {}
        gameservers_root = str(cluster_fields.get("gameservers_root") or "").strip()
        steamcmd_root = self._resolve_effective_steamcmd_root(cluster_fields.get("steamcmd_root"))

        results = [
            {
                "id": "gameservers_root",
                "label": "GameServers Root",
                "status": "installed" if gameservers_root else "missing",
                "details": gameservers_root or "gameservers_root is not configured.",
                "guidance": {"action": "open_app_settings", "label": "Open App Settings"},
            },
            {
                "id": "steamcmd_root",
                "label": "SteamCMD Root",
                "status": "installed" if steamcmd_root else "missing",
                "details": steamcmd_root or "steamcmd_root is not configured.",
                "guidance": {"action": "open_app_settings", "label": "Open App Settings"},
            },
        ]

        if not steamcmd_root:
            results.append(
                {
                    "id": "steamcmd",
                    "label": "SteamCMD",
                    "status": "missing",
                    "details": "steamcmd_root is not configured.",
                    "guidance": {"action": "open_app_settings", "label": "Open App Settings"},
                }
            )
        else:
            steamcmd_exe = os.path.join(steamcmd_root, "steamcmd.exe")
            failed_state = self._read_app_dependency_state("steamcmd")
            if os.path.isfile(steamcmd_exe):
                results.append(
                    {
                        "id": "steamcmd",
                        "label": "SteamCMD",
                        "status": "installed",
                        "details": steamcmd_exe,
                        "guidance": {"action": "install_steamcmd", "label": "Install SteamCMD"},
                    }
                )
            elif failed_state:
                results.append(
                    {
                        "id": "steamcmd",
                        "label": "SteamCMD",
                        "status": "install_failed",
                        "details": failed_state,
                        "guidance": {"action": "install_steamcmd", "label": "Install SteamCMD"},
                    }
                )
            else:
                results.append(
                    {
                        "id": "steamcmd",
                        "label": "SteamCMD",
                        "status": "install_available",
                        "details": steamcmd_root,
                        "guidance": {"action": "install_steamcmd", "label": "Install SteamCMD"},
                    }
                )

        statuses = {str(item.get("status") or "missing") for item in results}
        if "install_failed" in statuses:
            overall = "install_failed"
        elif "install_available" in statuses:
            overall = "install_available"
        elif "missing" in statuses:
            overall = "missing"
        else:
            overall = "installed"

        self._cached_app_setup_report = {"status": overall, "results": results}
        self._app_setup_dirty = False
        return dict(self._cached_app_setup_report)

    def refresh_app_setup_report(self):
        return self._recompute_app_setup_report()

    def read_cached_app_setup_report(self):
        if isinstance(self._cached_app_setup_report, dict):
            return dict(self._cached_app_setup_report)
        return {"status": "missing", "results": []}

    def _recompute_instance_readiness_report(self, plugin_name, instance_id):
        response = self.send_action(
            str(plugin_name),
            "validate",
            {"instance_id": str(instance_id), "strict": True, "live_probe": False},
        )
        report = {
            "ok": True,
            "plugin_name": str(plugin_name),
            "instance_id": str(instance_id),
            "status": "installed",
            "results": [],
        }
        if not isinstance(response, dict) or response.get("status") != "success":
            report["ok"] = False
            report["status"] = "missing"
            return report

        data = response.get("data") if isinstance(response.get("data"), dict) else {}
        checks = list(data.get("checks") or [])
        allowed_check_ids = {"launch_required_fields", "install_root", "ports_declared"}
        results = []
        for check in checks:
            if not isinstance(check, dict):
                continue
            if bool(check.get("ok")):
                continue
            check_id = str(check.get("id") or "").strip().lower()
            if check_id not in allowed_check_ids:
                continue
            results.append(
                {
                    "label": str(check.get("id") or "requirement"),
                    "status": "missing",
                    "details": str(check.get("details") or "").strip(),
                }
            )
        if results:
            report["status"] = "missing"
        report["results"] = results
        key = self._instance_readiness_key(plugin_name, instance_id)
        self._cached_instance_readiness_reports[key] = dict(report)
        self._dirty_instance_readiness.discard(key)
        self._dirty_instance_readiness_plugins.discard(str(plugin_name))
        if not self._dirty_instance_readiness and not self._dirty_instance_readiness_plugins:
            self._instance_readiness_dirty_all = False
        return dict(report)

    def refresh_instance_readiness_report(self, plugin_name, instance_id):
        return self._recompute_instance_readiness_report(plugin_name, instance_id)

    def read_cached_instance_readiness_report(self, plugin_name, instance_id):
        key = self._instance_readiness_key(plugin_name, instance_id)
        cached = self._cached_instance_readiness_reports.get(key)
        if isinstance(cached, dict):
            return dict(cached)
        return {
            "ok": True,
            "plugin_name": str(plugin_name),
            "instance_id": str(instance_id),
            "status": "installed",
            "results": [],
        }

    def get_plugin_dependency_report(self, plugin_name=None):
        from core.plugin_config import load_plugin_defaults

        plugin_names = [str(plugin_name)] if plugin_name else [str(name) for name in self._registry.list_all()]
        plugins = {}
        for name in plugin_names:
            metadata = self._registry.get_metadata(name) if hasattr(self._registry, "get_metadata") else {}
            declared = metadata.get("dependencies")
            items = list(declared) if isinstance(declared, list) else []
            try:
                defaults = load_plugin_defaults(str(self._cluster_root), str(name)) if self._cluster_root else {}
            except Exception:
                defaults = {}
            results = [self._evaluate_declared_dependency(name, item, defaults) for item in items]
            statuses = {str(result.get("status") or "missing") for result in results}
            if "install_failed" in statuses:
                overall = "install_failed"
            elif "install_available" in statuses:
                overall = "install_available"
            elif "missing" in statuses:
                overall = "missing"
            else:
                overall = "installed"
            plugins[name] = {
                "declared": items,
                "status": overall,
                "results": results,
            }
        return {"plugins": plugins}

    def _recompute_plugin_readiness_report(self, plugin_name):
        from core.plugin_config import load_plugin_defaults

        plugin_name = str(plugin_name)
        results = []
        try:
            loaded = load_plugin_defaults(str(self._cluster_root), plugin_name) if self._cluster_root else {}
            load_ok = True
            load_message = ""
        except Exception as exc:
            loaded = {}
            load_ok = False
            load_message = str(exc)

        if not load_ok:
            results.append(
                {
                    "label": "Plugin Settings",
                    "status": "missing",
                    "details": load_message or "Plugin settings could not be loaded.",
                    "guidance": {"action": "open_plugin_settings", "label": "Open Plugin Settings"},
                }
            )
        else:
            fields = dict(loaded or {})
            if not str(fields.get("install_root") or "").strip():
                results.append(
                    {
                        "label": "Install Root",
                        "status": "missing",
                        "details": "install_root must be configured before the plugin can be used.",
                        "guidance": {"action": "open_plugin_settings", "label": "Open Plugin Settings"},
                    }
                )
            if not str(fields.get("admin_password") or "").strip():
                results.append(
                    {
                        "label": "Admin Password",
                        "status": "missing",
                        "details": "admin_password must be configured before the plugin can be used.",
                        "guidance": {"action": "open_plugin_settings", "label": "Open Plugin Settings"},
                    }
                )
            if bool(fields.get("test_mode")):
                results.append(
                    {
                        "label": "Production Mode",
                        "status": "missing",
                        "details": "test_mode must be disabled before the plugin can be used.",
                        "guidance": {"action": "open_plugin_settings", "label": "Open Plugin Settings"},
                    }
                )

        dep_report = self.get_plugin_dependency_report(plugin_name)
        plugin_report = (dep_report.get("plugins") or {}).get(plugin_name)
        if isinstance(plugin_report, dict):
            for item in list(plugin_report.get("results") or []):
                if not isinstance(item, dict):
                    continue
                item_status = str(item.get("status") or "missing").strip().lower()
                if item_status == "installed":
                    continue
                normalized = dict(item)
                guidance = normalized.get("guidance")
                normalized["guidance"] = dict(guidance) if isinstance(guidance, dict) else None
                results.append(normalized)

        statuses = {str(item.get("status") or "missing").strip().lower() for item in results}
        if "install_failed" in statuses:
            overall = "install_failed"
        elif "install_available" in statuses:
            overall = "install_available"
        elif "missing" in statuses:
            overall = "missing"
        else:
            overall = "installed"

        report = {"plugin_name": plugin_name, "status": overall, "results": results}
        self._cached_plugin_readiness_reports[plugin_name] = dict(report)
        self._dirty_plugin_readiness.discard(plugin_name)
        if not self._dirty_plugin_readiness:
            self._plugin_readiness_dirty_all = False
        return dict(report)

    def refresh_plugin_readiness_report(self, plugin_name):
        return self._recompute_plugin_readiness_report(plugin_name)

    def read_cached_plugin_readiness_report(self, plugin_name):
        plugin_name = str(plugin_name)
        cached = self._cached_plugin_readiness_reports.get(plugin_name)
        if isinstance(cached, dict):
            return dict(cached)
        return {"plugin_name": plugin_name, "status": "installed", "results": []}

    def get_plugin_readiness_report(self, plugin_name):
        plugin_name = str(plugin_name)
        cached = self._cached_plugin_readiness_reports.get(plugin_name)
        if isinstance(cached, dict):
            return dict(cached)
        return self._recompute_plugin_readiness_report(plugin_name)

    def get_app_setup_report(self):
        if not isinstance(self._cached_app_setup_report, dict):
            return self._recompute_app_setup_report()
        return self.read_cached_app_setup_report()

    def get_instance_readiness_report(self, plugin_name, instance_id):
        key = self._instance_readiness_key(plugin_name, instance_id)
        cached = self._cached_instance_readiness_reports.get(key)
        if isinstance(cached, dict):
            return dict(cached)
        return self._recompute_instance_readiness_report(plugin_name, instance_id)

    def _steamcmd_install_readiness_error(self, plugin_name):
        report = self.get_plugin_dependency_report(str(plugin_name))
        plugin_report = (report.get("plugins") or {}).get(str(plugin_name))
        if not isinstance(plugin_report, dict):
            return ""

        for item in list(plugin_report.get("results") or []):
            if not isinstance(item, dict):
                continue
            if str(item.get("id") or "").strip().lower() != "steamcmd":
                continue

            status = str(item.get("status") or "missing").strip().lower()
            if status == "installed":
                return ""

            label = str(item.get("label") or "SteamCMD").strip() or "SteamCMD"
            details = str(item.get("details") or "").strip()
            if status == "install_available":
                return f"{label} is not installed yet. Install SteamCMD to: {details}"
            if status == "install_failed":
                return f"{label} install failed: {details}" if details else f"{label} install failed."
            if details:
                return f"{label} not ready: {details}"
            return f"{label} not ready."

        return ""

    def install_steamcmd(self):
        from core.steamcmd import install_windows_bootstrap

        if os.name != "nt":
            return {"status": "error", "message": "SteamCMD install is supported only on Windows."}

        cluster_fields = self._load_cluster_config_fields() or {}
        steamcmd_root = self._resolve_effective_steamcmd_root(cluster_fields.get("steamcmd_root"))
        if not steamcmd_root:
            return {"status": "error", "message": "SteamCMD Root is blank. Set it in App Settings first."}

        result = install_windows_bootstrap(steamcmd_root)
        if result.get("ok") is True:
            self._clear_app_dependency_state("steamcmd")
            response = {
                "status": "success",
                "data": {
                    "ok": True,
                    "details": str(result.get("message") or "SteamCMD installed successfully."),
                    "steamcmd_root": str(result.get("steamcmd_root") or steamcmd_root),
                    "steamcmd_exe": str(result.get("steamcmd_exe") or ""),
                    "installed_now": bool(result.get("installed_now")),
                },
            }
            self._recompute_app_setup_report()
            return response

        self._set_app_dependency_failed("steamcmd", str(result.get("message") or "SteamCMD install failed."))
        return {
            "status": "error",
            "message": str(result.get("message") or "SteamCMD install failed."),
            "data": {
                "ok": False,
                "details": str(result.get("message") or "SteamCMD install failed."),
                "steamcmd_root": steamcmd_root,
                "steamcmd_exe": "",
            },
        }

    def activate_plugin_source(self, source_dir):
        import json
        import shutil
        from pathlib import Path

        if not self._cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}

        source_path = Path(str(source_dir or "")).expanduser()
        if not source_path.exists() or not source_path.is_dir():
            return {"status": "error", "message": "Plugin folder not found"}

        plugin_json_path = source_path / "plugin.json"
        if not plugin_json_path.exists() or not plugin_json_path.is_file():
            return {"status": "error", "message": "Selected folder is missing plugin.json"}

        try:
            metadata = json.loads(plugin_json_path.read_text(encoding="utf-8-sig"))
        except Exception as e:
            return {"status": "error", "message": f"Failed to read plugin.json: {e}"}
        if not isinstance(metadata, dict):
            return {"status": "error", "message": "plugin.json must contain an object"}

        plugin_name = str(metadata.get("name") or source_path.name).strip()
        if not plugin_name:
            return {"status": "error", "message": "Plugin name is required"}

        plugins_root = Path(str(self._cluster_root)) / "plugins"
        plugins_root.mkdir(parents=True, exist_ok=True)
        destination = plugins_root / source_path.name
        if destination.exists():
            return {"status": "error", "message": f"Plugin folder already exists: {destination}"}

        try:
            shutil.copytree(str(source_path), str(destination), ignore=shutil.ignore_patterns("instances", "__pycache__"))
        except Exception as e:
            return {"status": "error", "message": f"Plugin activation failed: {e}"}

        self.load_plugins()
        return {"status": "success", "data": {"plugin_name": plugin_name, "plugin_path": str(destination)}}


    ############################################################
    # SECTION: Controlled Routing
    ############################################################
    def send_action(self, plugin_name, action, payload=None):

        payload = payload or {}

        plugin = self._registry.get(plugin_name)

        if not plugin:
            raise ValueError(f"Plugin '{plugin_name}' not found.")

        # New path: data-driven PluginHandler
        if "handler" in plugin:
            return plugin["handler"].handle(action, payload)

        # Existing path: IPC subprocess
        connection = plugin["connection"]

        response = connection.send_request(action, payload)

        return response

    def _resp_ok(self, resp) -> bool:
        return (
            isinstance(resp, dict)
            and resp.get("status") == "success"
            and isinstance(resp.get("data"), dict)
            and resp["data"].get("ok") is True
            and resp["data"].get("simulated") is not True
        )

    @staticmethod
    def _coerce_non_negative_int(value, default: int) -> int:
        try:
            out = int(value)
        except Exception:
            return int(default)
        return out if out >= 0 else int(default)

    def _load_update_policy(self, plugin_name):
        warning_minutes = int(_DEFAULT_UPDATE_WARNING_MINUTES)
        interval_minutes = int(_DEFAULT_UPDATE_WARNING_INTERVAL_MINUTES)

        cluster_root = getattr(self, "_cluster_root", None)
        if cluster_root:
            try:
                defaults = load_plugin_defaults(str(cluster_root), str(plugin_name))
            except Exception:
                defaults = {}
            if isinstance(defaults, dict):
                warning_minutes = self._coerce_non_negative_int(
                    defaults.get("update_warning_minutes"),
                    warning_minutes,
                )
                interval_minutes = self._coerce_non_negative_int(
                    defaults.get("update_warning_interval_minutes"),
                    interval_minutes,
                )

        if warning_minutes <= 0:
            interval_minutes = 0
        elif interval_minutes <= 0:
            interval_minutes = warning_minutes
        elif interval_minutes > warning_minutes:
            interval_minutes = warning_minutes

        return {
            "warning_minutes": int(warning_minutes),
            "interval_minutes": int(interval_minutes),
        }

    def _send_update_warning(self, plugin_name, instance_id, minutes_remaining: int):
        minutes = int(minutes_remaining)
        if minutes == 1:
            message = "Server update in 1 minute. Please prepare to disconnect."
        else:
            message = f"Server update in {minutes} minutes. Please prepare to disconnect."
        return self.send_action(
            str(plugin_name),
            "rcon_exec",
            {
                "instance_id": str(instance_id),
                "command": f"ServerChat {message}",
            },
        )

    ############################################################
    # SECTION: Explicit Install (No Start Side Effects)
    # Purpose:
    #     Run deterministic stub installer without starting server.
    # Constraints:
    #     - STOPPED-only
    #     - No STARTING/RUNNING transitions
    #     - Emits install_started/install_completed/install_failed
    ############################################################
    def install_instance(self, plugin_name, instance_id):

        self._state_manager.ensure_instance_exists(plugin_name, instance_id)
        current_state = self._state_manager.get_state(plugin_name, instance_id)

        if current_state == self._state_manager.DISABLED:
            return {"status": "error", "message": "Instance is DISABLED"}

        # Safety: STOPPED-only
        if current_state not in (self._state_manager.STOPPED,):
            return {"status": "error", "message": "Install allowed only when instance is STOPPED"}

        cluster_root = getattr(self, "_cluster_root", None)
        if not cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}

        # Informational install attempt start
        self._emit_event(
            EVENT_INSTALL_STARTED,
            plugin_name,
            instance_id,
        )

        install_result = ensure_installed(cluster_root, plugin_name, instance_id)

        if install_result.get("status") == "INSTALLED":
            self._emit_event(
                EVENT_INSTALL_COMPLETED,
                plugin_name,
                instance_id,
                payload={"install_status": "INSTALLED"},
            )
            # Ensure STOPPED remains asserted
            self._state_manager.set_state(plugin_name, instance_id, self._state_manager.STOPPED)
            self._mark_instance_readiness_dirty(plugin_name, instance_id)
            return {"status": "success", "install_status": "INSTALLED"}

        payload = {"install_status": "FAILED"}
        if install_result.get("message") == "Forced install failure":
            payload["reason"] = "FORCED_FAILURE"

        # Ensure STOPPED remains asserted (no STARTING/RUNNING transition)
        self._state_manager.set_state(plugin_name, instance_id, self._state_manager.STOPPED)

        self._emit_event(
            EVENT_INSTALL_FAILED,
            plugin_name,
            instance_id,
            payload=payload,
        )
        self._mark_instance_readiness_dirty(plugin_name, instance_id)

        return {"status": "error", "message": "Install failed"}

    def check_update(self, plugin_name, instance_id):

        self._load_version_build_map()
        self._state_manager.ensure_instance_exists(plugin_name, instance_id)
        response = self.send_action(
            str(plugin_name),
            "check_update",
            {"instance_id": str(instance_id), "install_target": "master"},
        )
        if not isinstance(response, dict):
            return response
        data = response.get("data")
        if not isinstance(data, dict):
            return response
        master_fields = self._resolved_master_update_fields(plugin_name, data)
        instance_fields = self._instance_update_compare_fields(
            plugin_name,
            instance_id,
            master_current_version=master_fields["master_current_version"],
            target_version=master_fields["target_version"],
        )
        enriched = dict(response)
        enriched["data"] = dict(data)
        enriched["data"].update(master_fields)
        enriched["data"].update(instance_fields)
        return enriched

    def check_plugin_update(self, plugin_name):
        self._load_version_build_map()
        response = self.send_action(
            str(plugin_name),
            "check_update",
            {"install_target": "master"},
        )
        if not isinstance(response, dict):
            return response
        data = response.get("data")
        if not isinstance(data, dict):
            return response
        master_fields = self._resolved_master_update_fields(plugin_name, data)
        instances = {}
        for instance_id in self._configured_instance_ids(plugin_name):
            instance_fields = self._instance_update_compare_fields(
                plugin_name,
                instance_id,
                master_current_version=master_fields["master_current_version"],
                target_version=master_fields["target_version"],
            )
            instance_payload = dict(instance_fields)
            instance_payload["master_current_version"] = master_fields["master_current_version"]
            instance_payload["master_current_build_id"] = master_fields["master_current_build_id"]
            instance_payload["target_version"] = master_fields["target_version"]
            instances[str(instance_id)] = instance_payload

        enriched = dict(response)
        enriched["data"] = dict(data)
        enriched["data"].update(master_fields)
        enriched["data"]["instances"] = instances
        return enriched

    def prepare_master_install(self, plugin_name):

        cluster_root = getattr(self, "_cluster_root", None)
        if not cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}

        steamcmd_readiness_error = self._steamcmd_install_readiness_error(plugin_name)
        if steamcmd_readiness_error:
            return {
                "status": "error",
                "message": steamcmd_readiness_error,
                "data": {
                    "ok": False,
                    "details": steamcmd_readiness_error,
                    "warnings": [],
                    "errors": [steamcmd_readiness_error],
                },
            }

        response = self.send_action(
            str(plugin_name),
            "install_server",
            {"install_target": "master"},
        )

        if isinstance(response, dict):
            out = dict(response)
            data = out.get("data") if isinstance(out.get("data"), dict) else {}
            data = dict(data)
            data["install_target"] = "master"
            out["data"] = data
            return out

        return {
            "status": "error",
            "message": "install_server returned invalid response",
            "data": {
                "ok": False,
                "install_target": "master",
                "details": "install_server returned invalid response",
                "warnings": [],
                "errors": ["install_server returned invalid response"],
            },
        }

    def discover_servers(self, plugin_name):

        return self.send_action(
            str(plugin_name),
            "discover_servers",
            {},
        )
    def install_server_instance(self, plugin_name, instance_id):

        self._state_manager.ensure_instance_exists(plugin_name, instance_id)
        current_state = self._state_manager.get_state(plugin_name, instance_id)

        if current_state == self._state_manager.DISABLED:
            return {"status": "error", "message": "Instance is DISABLED"}

        if current_state not in (self._state_manager.STOPPED,):
            return {"status": "error", "message": "Install allowed only when instance is STOPPED"}

        cluster_root = getattr(self, "_cluster_root", None)
        if not cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}

        from core.instance_layout import write_instance_install_status

        steamcmd_readiness_error = self._steamcmd_install_readiness_error(plugin_name)
        if steamcmd_readiness_error:
            write_instance_install_status(cluster_root, plugin_name, instance_id, "FAILED")
            self._state_manager.set_state(plugin_name, instance_id, self._state_manager.STOPPED)
            self._mark_instance_readiness_dirty(plugin_name, instance_id)
            return {
                "status": "error",
                "message": steamcmd_readiness_error,
                "data": {
                    "ok": False,
                    "install_status": "FAILED",
                    "details": steamcmd_readiness_error,
                    "warnings": [],
                    "errors": [steamcmd_readiness_error],
                },
            }

        # Single source of truth for install gating.
        write_instance_install_status(cluster_root, plugin_name, instance_id, "INSTALLING")

        distributed = self._distribute_master_install_to_instance(plugin_name, instance_id)
        if isinstance(distributed, dict) and distributed.get("status") == "success":
            write_instance_install_status(cluster_root, plugin_name, instance_id, "INSTALLED")
            self._mark_instance_readiness_dirty(plugin_name, instance_id)
            self._state_manager.set_state(plugin_name, instance_id, self._state_manager.STOPPED)
            out = dict(distributed)
            data = out.get("data") if isinstance(out.get("data"), dict) else {}
            data = dict(data)
            data["install_status"] = "INSTALLED"
            out["data"] = data
            return out
        if isinstance(distributed, dict) and distributed.get("status") == "error":
            write_instance_install_status(cluster_root, plugin_name, instance_id, "FAILED")
            self._mark_instance_readiness_dirty(plugin_name, instance_id)
            self._state_manager.set_state(plugin_name, instance_id, self._state_manager.STOPPED)
            data = distributed.get("data") if isinstance(distributed.get("data"), dict) else {}
            out = dict(distributed)
            out["data"] = {
                **dict(data),
                "install_status": "FAILED",
            }
            return out

        response = self.send_action(
            plugin_name,
            "install_server",
            {"instance_id": str(instance_id)},
        )

        install_status = "FAILED"
        install_reason = ""
        if not isinstance(response, dict):
            install_reason = "install_server response not a dict"
        elif response.get("status") != "success":
            install_reason = f"install_server status != success (got {response.get('status')})"
        elif not isinstance(response.get("data"), dict):
            install_reason = "install_server response data is not a dict"
        elif response.get("data", {}).get("ok") is not True:
            install_reason = "install_server response data.ok must be true"
        else:
            install_status = "INSTALLED"

        write_instance_install_status(cluster_root, plugin_name, instance_id, install_status)
        self._mark_instance_readiness_dirty(plugin_name, instance_id)

        # Install must never transition lifecycle out of STOPPED.
        self._state_manager.set_state(plugin_name, instance_id, self._state_manager.STOPPED)

        if isinstance(response, dict):
            out = dict(response)
            data = out.get("data") if isinstance(out.get("data"), dict) else {}
            data = dict(data)
            data["install_status"] = install_status
            if install_reason:
                errs = data.get("errors")
                if not isinstance(errs, list):
                    errs = []
                errs = [str(x) for x in errs]
                if install_reason not in errs:
                    errs.append(install_reason)
                data["errors"] = errs
                if not data.get("details"):
                    data["details"] = install_reason
            out["data"] = data
            return out

        return {
            "status": "error",
            "message": "install_server returned invalid response",
            "data": {
                "install_status": install_status,
                "details": install_reason or "install_server returned invalid response",
                "errors": [install_reason or "install_server returned invalid response"],
            },
        }

    def _distribute_master_install_to_instance(self, plugin_name, instance_id):
        master_layout = self._resolve_master_install_layout(plugin_name)
        instance_layout = self._resolve_instance_install_layout(plugin_name, instance_id)
        if not isinstance(master_layout, dict) or not isinstance(instance_layout, dict):
            return None

        source_root = str(master_layout.get("server_dir") or "").strip()
        dest_root = str(instance_layout.get("server_dir") or "").strip()
        if not source_root or not dest_root:
            return None

        metadata = self._registry.get_metadata(str(plugin_name)) if hasattr(self._registry, "get_metadata") else {}
        executable_rel = str((metadata or {}).get("executable") or "").strip()
        if not executable_rel:
            return None

        source_exe = Path(source_root) / executable_rel.replace("/", os.sep).replace("\\", os.sep)
        if not source_exe.is_file():
            return None

        excludes = self._master_distribution_excludes(plugin_name)
        try:
            distribution = self._robocopy_master_install(Path(source_root), Path(dest_root), excludes)
        except Exception as e:
            return {
                "status": "error",
                "message": f"Master distribution failed: {e}",
                "data": {
                    "ok": False,
                    "details": f"Master distribution failed: {e}",
                    "warnings": [],
                    "errors": [f"Master distribution failed: {e}"],
                    "install_source": "master",
                },
            }

        return {
            "status": "success",
            "data": {
                "ok": True,
                "details": "install_server complete (distributed from prepared master).",
                "warnings": [],
                "errors": [],
                "install_source": "master",
                "distribution_method": str(distribution.get("method") or "robocopy"),
                "install_target": "instance",
                "master_install_root": str(source_root),
                "install_root": str(dest_root),
                "copied_files": int(distribution.get("copied_files") or 0),
            },
        }

    def _resolve_master_install_layout(self, plugin_name):
        from core.instance_layout import resolve_steam_game_master_layout

        metadata = self._registry.get_metadata(str(plugin_name)) if hasattr(self._registry, "get_metadata") else {}
        install_subfolder = str((metadata or {}).get("install_subfolder") or "").strip()
        if not install_subfolder or not self._cluster_root:
            return None
        defaults = load_plugin_defaults(str(self._cluster_root), str(plugin_name))
        cluster_fields = self._load_cluster_config_fields() or {}
        for key in ("steamcmd_root", "gameservers_root", "cluster_name"):
            if cluster_fields.get(key):
                defaults[key] = cluster_fields.get(key)
        return resolve_steam_game_master_layout(
            defaults,
            plugin_name=str(plugin_name),
            default_install_folder=install_subfolder,
        )

    def _resolve_instance_install_layout(self, plugin_name, instance_id):
        from core.instance_layout import resolve_steam_game_layout

        if not self._cluster_root:
            return None
        metadata = self._registry.get_metadata(str(plugin_name)) if hasattr(self._registry, "get_metadata") else {}
        install_subfolder = str((metadata or {}).get("install_subfolder") or "").strip()
        if not install_subfolder:
            return None
        defaults = load_plugin_defaults(str(self._cluster_root), str(plugin_name))
        cluster_fields = self._load_cluster_config_fields() or {}
        for key in ("steamcmd_root", "gameservers_root", "cluster_name"):
            if cluster_fields.get(key):
                defaults[key] = cluster_fields.get(key)
        inst = self._load_instance_layout_fields(plugin_name, instance_id)
        return resolve_steam_game_layout(
            defaults,
            inst,
            str(instance_id),
            default_install_folder=install_subfolder,
            default_cluster_name=install_subfolder.lower(),
            default_legacy_server_subdir="server",
        )

    def _load_instance_layout_fields(self, plugin_name, instance_id):
        if not self._cluster_root:
            return {}
        path = resolve_instance_config_path(str(self._cluster_root), str(plugin_name), str(instance_id))
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except Exception:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        try:
            normalized = load_instance_config(str(self._cluster_root), str(plugin_name), str(instance_id))
            if isinstance(normalized, dict):
                raw.update(normalized)
        except Exception:
            pass
        return raw

    def _master_distribution_excludes(self, plugin_name):
        metadata = self._registry.get_metadata(str(plugin_name)) if hasattr(self._registry, "get_metadata") else {}
        raw = (metadata or {}).get("master_distribution_excludes")
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw:
            text = str(item or "").strip().replace("/", os.sep).replace("\\", os.sep).strip("\\/")
            if text:
                out.append(text)
        return out

    def _configured_instance_ids(self, plugin_name):
        if not self._cluster_root:
            return []
        instances_root = Path(str(self._cluster_root)) / "plugins" / str(plugin_name) / "instances"
        if not instances_root.is_dir():
            return []
        out = []
        for child in sorted(instances_root.iterdir(), key=lambda p: p.name):
            if not child.is_dir():
                continue
            config_path = resolve_instance_config_path(str(self._cluster_root), str(plugin_name), str(child.name))
            if config_path.is_file():
                out.append(str(child.name))
        return out

    def _copy_tree_with_excludes(self, source_root: Path, dest_root: Path, excludes):
        source_root.mkdir(parents=True, exist_ok=True)
        dest_root.mkdir(parents=True, exist_ok=True)
        normalized_excludes = [str(item or "").strip().replace("/", os.sep).replace("\\", os.sep).strip("\\/") for item in (excludes or []) if str(item or "").strip()]

        def _is_excluded(rel_path: str) -> bool:
            rel_norm = str(rel_path or "").strip().replace("/", os.sep).replace("\\", os.sep).strip("\\/")
            if not rel_norm:
                return False
            for item in normalized_excludes:
                if rel_norm == item or rel_norm.startswith(item + os.sep):
                    return True
            return False

        copied_files = 0
        for root, dirs, files in os.walk(source_root):
            rel_root = os.path.relpath(root, source_root)
            rel_root = "" if rel_root == "." else str(rel_root)
            if _is_excluded(rel_root):
                dirs[:] = []
                continue
            dirs[:] = [name for name in dirs if not _is_excluded(os.path.join(rel_root, name))]
            target_dir = dest_root if not rel_root else dest_root / rel_root
            target_dir.mkdir(parents=True, exist_ok=True)
            for name in files:
                rel_file = os.path.join(rel_root, name) if rel_root else name
                if _is_excluded(rel_file):
                    continue
                shutil.copy2(Path(root) / name, target_dir / name)
                copied_files += 1
        return copied_files

    def _robocopy_master_install(self, source_root: Path, dest_root: Path, excludes):
        source_root.mkdir(parents=True, exist_ok=True)
        dest_root.mkdir(parents=True, exist_ok=True)

        command = [
            "robocopy",
            str(source_root),
            str(dest_root),
            "/E",
            "/R:1",
            "/W:1",
            "/NFL",
            "/NDL",
            "/NJH",
            "/NJS",
            "/NP",
        ]
        normalized_excludes = [
            str(item or "").strip().replace("/", os.sep).replace("\\", os.sep).strip("\\/")
            for item in (excludes or [])
            if str(item or "").strip()
        ]
        if normalized_excludes:
            command.append("/XD")
            for item in normalized_excludes:
                command.append(str(source_root / item))

        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            shell=False,
        )
        rc = int(completed.returncode)
        if rc > 7:
            stdout = str(completed.stdout or "").strip()
            stderr = str(completed.stderr or "").strip()
            detail = f"robocopy exited with code {rc}."
            if stderr:
                detail = f"{detail} {stderr}"
            elif stdout:
                detail = f"{detail} {stdout}"
            raise RuntimeError(detail)

        copied_files = 0
        try:
            copied_files = sum(1 for _ in dest_root.rglob("*") if _.is_file())
        except Exception:
            copied_files = 0
        return {
            "method": "robocopy",
            "returncode": rc,
            "copied_files": copied_files,
        }

    def update_instance(self, plugin_name, instance_id):

        self._state_manager.ensure_instance_exists(plugin_name, instance_id)
        current_state = self._state_manager.get_state(plugin_name, instance_id)

        if current_state == self._state_manager.DISABLED:
            return {"status": "error", "message": "Instance is DISABLED"}

        current_version_before_update = self._current_version_for_update_compare(plugin_name, instance_id)
        self._load_version_build_map()
        runtime_running = self._runtime_running(plugin_name, instance_id)
        if not runtime_running:
            return self.install_server_instance(plugin_name, instance_id)

        policy = self._load_update_policy(plugin_name)
        warnings = []

        warning_minutes = int(policy.get("warning_minutes", 0))
        interval_minutes = int(policy.get("interval_minutes", 0))
        if warning_minutes > 0:
            remaining_minutes = int(warning_minutes)
            while remaining_minutes > 0:
                rcon_response = self._send_update_warning(plugin_name, instance_id, remaining_minutes)
                if not self._resp_ok(rcon_response):
                    warning_message = f"Update warning broadcast failed at {remaining_minutes} minute(s)."
                    if isinstance(rcon_response, dict):
                        data = rcon_response.get("data")
                        if isinstance(data, dict):
                            errors = data.get("errors")
                            if isinstance(errors, list) and errors:
                                warning_message = str(errors[0])
                        elif rcon_response.get("message"):
                            warning_message = str(rcon_response.get("message"))
                    warnings.append(warning_message)
                if remaining_minutes <= interval_minutes:
                    break
                time.sleep(float(interval_minutes) * 60.0)
                remaining_minutes -= interval_minutes
            time.sleep(float(max(remaining_minutes, 0)) * 60.0)

        stop_response = self.stop_instance(plugin_name, instance_id)
        if not self._resp_ok(stop_response):
            if isinstance(stop_response, dict) and warnings:
                data = stop_response.get("data")
                if isinstance(data, dict):
                    merged = [str(x) for x in (data.get("warnings") or [])]
                    for item in warnings:
                        if item not in merged:
                            merged.append(item)
                    data["warnings"] = merged
            return stop_response

        runtime_running_after_stop = self._runtime_running(plugin_name, instance_id)
        if runtime_running_after_stop:
            return {
                "status": "error",
                "message": "Server is still shutting down.",
                "data": {
                    "ok": False,
                    "details": "Server is still shutting down.",
                    "warnings": warnings,
                    "errors": ["Server is still shutting down."],
                },
            }

        install_response = self.install_server_instance(plugin_name, instance_id)
        if not self._resp_ok(install_response):
            if isinstance(install_response, dict) and warnings:
                data = install_response.get("data")
                if isinstance(data, dict):
                    merged = [str(x) for x in (data.get("warnings") or [])]
                    for item in warnings:
                        if item not in merged:
                            merged.append(item)
                    data["warnings"] = merged
            return install_response

        install_data = install_response.get("data") if isinstance(install_response, dict) else None
        self._begin_update_verification(
            plugin_name,
            instance_id,
            previous_version=current_version_before_update,
            expected_build_id=self._stored_master_build_for_plugin(plugin_name),
            master_install_root=str((install_data or {}).get("master_install_root") or ""),
            install_root=str((install_data or {}).get("install_root") or ""),
        )

        start_response = self.start_instance(plugin_name, instance_id)
        if isinstance(start_response, dict) and warnings:
            data = start_response.get("data")
            if isinstance(data, dict):
                merged = [str(x) for x in (data.get("warnings") or [])]
                for item in warnings:
                    if item not in merged:
                        merged.append(item)
                data["warnings"] = merged
        if isinstance(start_response, dict):
            runtime_data = ((start_response.get("data") or {}) if isinstance(start_response.get("data"), dict) else {})
            failure = runtime_data.get("update_verification_failure")
            if isinstance(failure, dict):
                return {
                    "status": "error",
                    "message": str(failure.get("message") or "Update verification failed."),
                    "data": {
                        **runtime_data,
                        "ok": False,
                        "details": str(failure.get("message") or "Update verification failed."),
                        "errors": [str(failure.get("message") or "Update verification failed.")],
                        "update_verification_failure": dict(failure),
                    },
                }
        return start_response

    def start_instance(self, plugin_name, instance_id):

        self._state_manager.ensure_instance_exists(plugin_name, instance_id)
        current_state = self._state_manager.get_state(plugin_name, instance_id)

        if current_state == self._state_manager.DISABLED:
            return {"status": "error", "message": "Instance is DISABLED"}

        if current_state not in (self._state_manager.STOPPED,):
            return {"status": "error", "message": "Start not allowed in current state"}

        # ------------------------------------------
        # CG-PROVISION-2
        # Start requires explicit install (NO auto-install)
        # ------------------------------------------
        if self.get_instance_install_status(plugin_name, instance_id) != "INSTALLED":
            return {
                "status": "error",
                "message": "Instance not installed. Run: install <plugin> <instance>",
            }
        auto_update_response = self._apply_prepared_master_update_on_start(plugin_name, instance_id)
        if isinstance(auto_update_response, dict) and auto_update_response.get("_continue_start") is not True:
            return auto_update_response
        pending_sync = self.apply_pending_ini_sync_fields(plugin_name, instance_id)
        if not self._resp_ok(pending_sync):
            return pending_sync
        previous_summary = self.read_cached_runtime_summary(plugin_name, instance_id)
        metadata = self._registry.get_metadata(str(plugin_name)) if hasattr(self._registry, "get_metadata") else {}
        if isinstance(metadata, dict) and isinstance(metadata.get("ini_settings"), dict) and metadata.get("ini_settings"):
            startup_sync = self.send_action(
                plugin_name,
                "sync_ini_fields",
                {"instance_id": instance_id, "fields": list(_STARTUP_INI_SYNC_FIELDS)},
            )
            if not self._resp_ok(startup_sync):
                return startup_sync
        return self._start_transition(
            plugin_name,
            instance_id,
            previous_summary=previous_summary,
            last_action="start",
            transitional_state=self._state_manager.STARTING,
            emit_started_event=True,
            refresh_runtime_after_start=True,
            require_ok_payload=True,
        )

    def _apply_prepared_master_update_on_start(self, plugin_name, instance_id):
        if not self._auto_update_on_restart_enabled(plugin_name):
            return {"_continue_start": True}

        update_resp = self.check_update(plugin_name, instance_id)
        data = update_resp.get("data") if isinstance(update_resp, dict) else None
        if not isinstance(data, dict):
            return {"_continue_start": True}
        if not bool(data.get("master_install_ready")) or not bool(data.get("update_available")):
            return {"_continue_start": True}

        previous_version = self._current_version_for_update_compare(plugin_name, instance_id)
        install_resp = self.install_server_instance(plugin_name, instance_id)
        if self._resp_ok(install_resp):
            install_data = install_resp.get("data") if isinstance(install_resp, dict) else None
            self._begin_update_verification(
                plugin_name,
                instance_id,
                previous_version=previous_version,
                expected_build_id=str(data.get("master_current_build_id") or data.get("target_version") or ""),
                master_install_root=str((install_data or {}).get("master_install_root") or ""),
                install_root=str((install_data or {}).get("install_root") or ""),
            )
            return {"_continue_start": True}
        return install_resp

    def _start_transition(
        self,
        plugin_name,
        instance_id,
        *,
        previous_summary,
        last_action: str,
        transitional_state: str,
        emit_started_event: bool,
        refresh_runtime_after_start: bool,
        require_ok_payload: bool,
    ):
        self.set_instance_last_action(plugin_name, instance_id, last_action)
        self._state_manager.set_state(plugin_name, instance_id, transitional_state)

        response = self.send_action(plugin_name, "start", {"instance_id": instance_id})
        start_ok = self._resp_ok(response) if require_ok_payload else (
            isinstance(response, dict) and response.get("status") == "success"
        )
        if not start_ok:
            self._state_manager.set_state(plugin_name, instance_id, self._state_manager.STOPPED)
            return response

        if not refresh_runtime_after_start:
            self._state_manager.set_state(plugin_name, instance_id, self._state_manager.RUNNING)
            if emit_started_event:
                self._emit_event(EVENT_INSTANCE_STARTED, plugin_name, instance_id)
            return response
        current_summary = self._refresh_runtime_summary_after_start(plugin_name, instance_id)
        runtime_running = self._runtime_summary_running_state(current_summary)
        if runtime_running is not False:
            self._state_manager.set_state(plugin_name, instance_id, self._state_manager.RUNNING)
            if emit_started_event:
                self._emit_event(EVENT_INSTANCE_STARTED, plugin_name, instance_id)
        else:
            self._state_manager.set_state(plugin_name, instance_id, transitional_state)
        notice = self._build_started_version_notice(plugin_name, instance_id, previous_summary, current_summary)
        if notice and isinstance(response.get("data"), dict):
            details = str(response["data"].get("details") or "").strip()
            response["data"]["details"] = f"{details} {notice}".strip() if details else notice
        if isinstance(current_summary, dict):
            current_data = current_summary.get("data")
            failure = current_data.get("update_verification_failure") if isinstance(current_data, dict) else None
            if isinstance(failure, dict) and isinstance(response.get("data"), dict):
                response["data"]["update_verification_failure"] = dict(failure)
        return response

    def _graceful_stop_transition(
        self,
        plugin_name,
        instance_id,
        *,
        require_runtime_gate: bool,
        last_action: str,
        transitional_state: str,
        revert_state_on_failure: str,
        apply_pending_sync_when_stopped: bool,
        not_running_message: str,
        still_running_error_message: str | None = None,
    ):
        self._state_manager.ensure_instance_exists(plugin_name, instance_id)

        current_state = self._state_manager.get_state(plugin_name, instance_id)
        if current_state == self._state_manager.DISABLED:
            return {
                "status": "error",
                "message": "Instance is DISABLED"
            }

        if require_runtime_gate:
            runtime_running = self._runtime_running(plugin_name, instance_id)
            if not runtime_running:
                return {
                    "status": "error",
                    "message": not_running_message,
                }

        self.set_instance_last_action(plugin_name, instance_id, last_action)
        self._state_manager.set_state(
            plugin_name,
            instance_id,
            transitional_state,
        )
        self._set_stop_deadline(plugin_name, instance_id)

        response = self.send_action(
            plugin_name,
            "graceful_stop",
            {"instance_id": instance_id}
        )
        stop_ok = (
            isinstance(response, dict)
            and response.get("status") == "success"
            and isinstance(response.get("data"), dict)
            and response["data"].get("ok") is True
        )

        if not stop_ok:
            self._state_manager.set_state(plugin_name, instance_id, revert_state_on_failure)
            self._clear_stop_deadline(plugin_name, instance_id)
            return response

        if not require_runtime_gate:
            self._clear_stop_deadline(plugin_name, instance_id)
            return response

        if still_running_error_message:
            runtime_running_after_stop = self._runtime_running(plugin_name, instance_id)
            if runtime_running_after_stop:
                return {
                    "status": "error",
                    "message": still_running_error_message,
                }
            self._clear_stop_deadline(plugin_name, instance_id)
            return response

        reconcile = self.reconcile_stop_progress(plugin_name, instance_id)
        if isinstance(reconcile, dict) and reconcile.get("status") == "stopped":
            if apply_pending_sync_when_stopped:
                self.apply_pending_ini_sync_fields(plugin_name, instance_id)
            return response
        return response

    def _auto_update_on_restart_enabled(self, plugin_name):
        if not self._cluster_root:
            return False
        try:
            defaults = load_plugin_defaults(str(self._cluster_root), str(plugin_name))
        except Exception:
            return False
        return bool(defaults.get("auto_update_on_restart"))

    def stop_instance(self, plugin_name, instance_id):
        return self._graceful_stop_transition(
            plugin_name,
            instance_id,
            require_runtime_gate=True,
            last_action="stop",
            transitional_state=self._state_manager.STOPPING,
            revert_state_on_failure=self._state_manager.RUNNING,
            apply_pending_sync_when_stopped=True,
            not_running_message="Server is not running.",
        )

    def restart_instance(self, plugin_name, instance_id, restart_reason="crash"):


        key = (plugin_name, instance_id)

        if restart_reason == "crash" and key in self._crash_restart_paused:
            return {
                "status": "error",
                "message": "Crash restarts are paused for this instance"
            }

        stop_response = self._graceful_stop_transition(
            plugin_name,
            instance_id,
            require_runtime_gate=(restart_reason != "scheduled"),
            last_action="restart",
            transitional_state=self._state_manager.RESTARTING,
            revert_state_on_failure=self._state_manager.RUNNING,
            apply_pending_sync_when_stopped=False,
            not_running_message="Server is not running.",
            still_running_error_message=(
                "Server is still shutting down."
                if restart_reason != "scheduled"
                else None
            ),
        )
        if stop_response.get("status") != "success":
            return stop_response

        # Reset stability counter only for a successful scheduled restart stop phase.
        if restart_reason == "scheduled":
            key = self._ensure_counter_entry(plugin_name, instance_id)
            self._crash_counters[key]["crash_stability_count"] = 0

        start_response = self._start_transition(
            plugin_name,
            instance_id,
            previous_summary=self.read_cached_runtime_summary(plugin_name, instance_id),
            last_action="restart",
            transitional_state=self._state_manager.RESTARTING,
            emit_started_event=False,
            refresh_runtime_after_start=(restart_reason != "scheduled"),
            require_ok_payload=False,
        )
        if start_response.get("status") != "success":
            return start_response

        # Layer 7-3: record last restart metadata ONLY on successful restart
        self._last_restart_metadata[(plugin_name, instance_id)] = {
            "last_restart_source": restart_reason,
            "last_restart_time": int(self._restart_clock),
        }
        self._restart_clock += 1

        self._emit_event(
            EVENT_INSTANCE_RESTARTED,
            plugin_name,
            instance_id,
            payload={"reason": restart_reason},
        )

        return start_response

    def disable_instance(self, plugin_name, instance_id, reason="manual"):
        self._state_manager.ensure_instance_exists(plugin_name, instance_id)
        self._state_manager.set_state(
            plugin_name,
            instance_id,
            self._state_manager.DISABLED
        )

        self._emit_event(
            EVENT_INSTANCE_DISABLED,
            plugin_name,
            instance_id,
            payload={"reason": reason},
        )

        return {"status": "success", "message": f"Disabled: {reason}"}

    def reenable_instance(self, plugin_name, instance_id, reason="manual"):


        self._state_manager.ensure_instance_exists(plugin_name, instance_id)



        # Reset crash counter (instrumentation counter)
        self.reset_crash_total_count(plugin_name, instance_id)

        # Transition state to STOPPED (no auto-start)
        self._state_manager.set_state(
            plugin_name,
            instance_id,
            self._state_manager.STOPPED
        )

        self._emit_event(
            EVENT_INSTANCE_ENABLED,
            plugin_name,
            instance_id,
            payload={"reason": reason},
        )

        return {"status": "success", "message": f"Re-enabled: {reason}"}

    def _purge_instance_runtime_state(self, plugin_name: str, instance_id: str) -> None:
        key = (str(plugin_name), str(instance_id))
        readiness_key = self._instance_readiness_key(plugin_name, instance_id)
        self._cached_runtime_summaries.pop(key, None)
        self._runtime_summary_last_updated.pop(key, None)
        self._runtime_summary_inflight.discard(key)
        self._cached_runtime_inspects.pop(key, None)
        self._runtime_inspect_last_updated.pop(key, None)
        self._runtime_inspect_inflight.discard(key)
        self._cached_instance_readiness_reports.pop(readiness_key, None)
        self._dirty_instance_readiness.discard(readiness_key)
        self._pending_update_verifications.pop(key, None)
        self._pending_update_verification_notifications.pop(key, None)
        self._crash_counters.pop(key, None)
        self._crash_restart_paused.discard(key)
        self._instance_last_action.pop(key, None)
        self._stop_deadlines.pop(key, None)
        self._last_restart_metadata.pop(key, None)
        self._state_manager.remove_instance(plugin_name, instance_id)

    def remove_instance(self, plugin_name, instance_id, delete_files: bool = False):
        if not self._cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}

        plugin_name = str(plugin_name)
        instance_id = str(instance_id)
        self._state_manager.ensure_instance_exists(plugin_name, instance_id)
        current_state = str(self._state_manager.get_state(plugin_name, instance_id) or "")
        runtime_running = bool(self._runtime_running(plugin_name, instance_id))
        if runtime_running or current_state not in {self._state_manager.STOPPED, self._state_manager.DISABLED}:
            return {"status": "error", "message": "Server must be stopped before it can be removed"}

        instance_root = Path(str(self._cluster_root)) / "plugins" / plugin_name / "instances" / instance_id
        install_root_path: Path | None = None
        layout = self._resolve_instance_install_layout(plugin_name, instance_id)
        if isinstance(layout, dict):
            install_root_text = str(layout.get("install_root") or "").strip()
            if install_root_text:
                install_root_path = Path(install_root_text)
                if not install_root_path.is_absolute():
                    install_root_path = (Path(str(self._cluster_root)) / install_root_path).resolve()

        try:
            if delete_files and install_root_path is not None and install_root_path.exists() and install_root_path.is_dir():
                shutil.rmtree(install_root_path, ignore_errors=False)
            if instance_root.exists() and instance_root.is_dir():
                shutil.rmtree(instance_root, ignore_errors=False)
        except Exception as exc:
            return {"status": "error", "message": f"Remove failed: {exc}"}

        self._purge_instance_runtime_state(plugin_name, instance_id)
        return {
            "status": "success",
            "data": {
                "ok": True,
                "plugin_name": plugin_name,
                "instance_id": instance_id,
                "delete_files": bool(delete_files),
                "instance_root": str(instance_root),
                "install_root": str(install_root_path or ""),
            },
        }

    ############################################################
    # SECTION: Manual Event Polling
    ############################################################
    def poll_events(self):
        handled_events = []

        plugin_names = self._registry.list_all()

        for plugin_name in plugin_names:

            plugin = self._registry.get(plugin_name)
            if not plugin:
                continue

            connection = plugin.get("connection")
            if not connection:
                continue

            events = connection.drain_events()

            for message in events:
                if message.get("type") != "event":
                    continue

                self._handle_event(plugin_name, message)
                handled_events.append({"plugin_name": str(plugin_name), "event_type": str(message.get("event_type") or "")})
        return handled_events

    ############################################################
    # SECTION: Event Dispatch Routing
    ############################################################
    def _handle_event(self, plugin_name: str, message: dict):

        event_type = message.get("event_type")
        data = message.get("data", {})

        if event_type == "instance_crashed":
            instance_id = data.get("instance_id")
            self._handle_instance_crashed(plugin_name, instance_id)

    ############################################################
    # SECTION: Crash Handling With Threshold Enforcement
    # Purpose:
    # Enforce per-instance crash threshold deterministically.
    # Lifecycle Ownership:
    # Orchestrator (Core)
    # Phase:
    # Crash Architecture - Phase 3 (Threshold Enforcement)
    # Constraints:
    # - No persistence.
    # - No time windows.
    # - No backoff logic.
    ############################################################
    def _handle_instance_crashed(self, plugin_name: str, instance_id: str):

        if not instance_id:
            return

        current_state = self._state_manager.get_state(plugin_name, instance_id)

        if current_state != self._state_manager.RUNNING:
            return

        key = self._ensure_counter_entry(plugin_name, instance_id)

        effective_threshold = self.get_effective_threshold(plugin_name, instance_id)


        # Increment both counters
        self._crash_counters[key]["crash_total_count"] += 1
        self._crash_counters[key]["crash_stability_count"] += 1

        self._emit_event(
            EVENT_INSTANCE_CRASHED,
            plugin_name,
            instance_id,
        )

        # Enforce: once crash_count >= threshold, stop further crash restarts.
        # crash_count is crash_total_count (instrumentation counter).
        if self._crash_counters[key]["crash_total_count"] >= effective_threshold:
            self._crash_restart_paused.add((plugin_name, instance_id))

            # Instance crashed; prevent RUNNING from remaining asserted.
            # Use STOPPED (not DISABLED) so manual start remains legal.
            self._state_manager.set_state(
                plugin_name,
                instance_id,
                self._state_manager.STOPPED
            )

            self._emit_event(
                EVENT_CRASH_THRESHOLD_REACHED,
                plugin_name,
                instance_id,
            )
            return

        self.restart_instance(plugin_name, instance_id, restart_reason="crash")

    ############################################################
    # SECTION: Clean Shutdown
    ############################################################
    def shutdown_plugin(self, plugin_name):

        plugin = self._registry.get(plugin_name)

        if not plugin:
            return

        if "handler" in plugin:
            plugin["handler"].handle("shutdown", {})
            return

        connection = plugin["connection"]
        process = plugin["process"]

        connection.send_request("shutdown", {})
        process.join()

    # ------------------------------------------------------------
    # Layer 6: Persistence (Durability only; no policy execution)
    # ------------------------------------------------------------

    @staticmethod
    def _encode_key(plugin_name: str, instance_id: str) -> str:
        return f"{plugin_name}::{instance_id}"

    @staticmethod
    def _decode_key(encoded: str):
        if "::" not in encoded:
            raise ValueError(f"Invalid encoded key: {encoded}")
        plugin_name, instance_id = encoded.split("::", 1)
        return plugin_name, instance_id

    def _build_persist_snapshot(self) -> dict:
        # Lifecycle snapshot: read StateManager internal storage.
        # We avoid modifying StateManager API (durability only).
        lifecycle: dict[str, dict[str, Any]] = {}
        raw_state = getattr(self._state_manager, "_state", {}) or {}
        for plugin_name, instances in raw_state.items():
            lifecycle[plugin_name] = {}
            for instance_id, payload in (instances or {}).items():
                lifecycle[plugin_name][instance_id] = payload.get("state")

        # Crash counters: tuple-key dict -> encoded key dict
        crash_counters = {}
        for (plugin_name, instance_id), data in self._crash_counters.items():
            crash_counters[self._encode_key(plugin_name, instance_id)] = {
                "crash_total_count": int(data.get("crash_total_count", 0)),
                "crash_stability_count": int(data.get("crash_stability_count", 0)),
            }

        # Threshold overrides
        thresholds = {
            "global": int(self._global_threshold),
            "plugins": {k: int(v) for k, v in self._plugin_thresholds.items()},
            "instances": {
                self._encode_key(p, i): int(v)
                for (p, i), v in self._instance_thresholds.items()
            },
        }
        # Last restart metadata: tuple-key dict -> encoded key dict
        restart_metadata = {}
        for (plugin_name, instance_id), meta in self._last_restart_metadata.items():
            restart_metadata[self._encode_key(plugin_name, instance_id)] = {
                "last_restart_source": meta.get("last_restart_source"),
                "last_restart_time": int(meta.get("last_restart_time", 0)),
            }

        return {
            "lifecycle": lifecycle,
            "crash_counters": crash_counters,
            "thresholds": thresholds,
            "restart_metadata": restart_metadata,
        }

    def _restore_from_persistence(self) -> None:
        payload = self._persistence.load()

        # Restore lifecycle state (passive, no transitions)
        lifecycle = payload.get("lifecycle", {}) or {}
        for plugin_name, instances in lifecycle.items():
            for instance_id, state in (instances or {}).items():
                self._state_manager.ensure_instance_exists(plugin_name, instance_id)
                self._state_manager.set_state(plugin_name, instance_id, state)

        # Restore crash counters (passive)
        self._crash_counters = {}
        crash_counters = payload.get("crash_counters", {}) or {}
        for encoded_key, data in crash_counters.items():
            plugin_name, instance_id = self._decode_key(encoded_key)
            self._crash_counters[(plugin_name, instance_id)] = {
                "crash_total_count": int(data.get("crash_total_count", 0)),
                "crash_stability_count": int(data.get("crash_stability_count", 0)),
            }

        # Restore thresholds (passive)
        thresholds = payload.get("thresholds", {}) or {}
        if "global" in thresholds:
            self._global_threshold = int(thresholds["global"])

        self._plugin_thresholds = {
            k: int(v) for k, v in (thresholds.get("plugins", {}) or {}).items()
        }

        self._instance_thresholds = {}
        for encoded_key, v in (thresholds.get("instances", {}) or {}).items():
            p, i = self._decode_key(encoded_key)
            self._instance_thresholds[(p, i)] = int(v)

        # Layer 6-2:
        # Derive crash-restart pause deterministically from restored
        # counters and thresholds. No policy execution occurs here.
        self._derive_crash_restart_paused_from_persisted_state()

        # ----------------------------
        # Layer 7-3: Restore last restart metadata (passive)
        # ----------------------------
        self._last_restart_metadata = {}
        restart_metadata = payload.get("restart_metadata", {}) or {}

        max_time = -1
        for encoded_key, meta in restart_metadata.items():
            plugin_name, instance_id = self._decode_key(encoded_key)

            source = meta.get("last_restart_source")
            t = int(meta.get("last_restart_time", 0))

            self._last_restart_metadata[(plugin_name, instance_id)] = {
                "last_restart_source": source,
                "last_restart_time": t,
            }

            if t > max_time:
                max_time = t

        # Deterministic logical clock continues from restored max+1
        self._restart_clock = max_time + 1 if max_time >= 0 else 0

    def persist_state(self) -> None:
        if not self._persistence:
            raise ValueError("Persistence disabled (no persistence_path provided)")
        snapshot = self._build_persist_snapshot()
        self._persistence.save(snapshot)

    def _port_policy_starts(self, plugin_name: str):
        defaults = load_plugin_defaults(str(self._cluster_root), str(plugin_name))
        game_start = defaults.get("default_game_port_start", 30000)
        rcon_start = defaults.get("default_rcon_port_start", 31000)
        try:
            game_start = int(game_start)
        except Exception:
            game_start = 30000
        try:
            rcon_start = int(rcon_start)
        except Exception:
            rcon_start = 31000
        if game_start < 1 or game_start > 65535:
            game_start = 30000
        if rcon_start < 1 or rcon_start > 65535:
            rcon_start = 31000
        return {
            "game_port": int(game_start),
            "rcon_port": int(rcon_start),
        }

    def _used_managed_ports(self, plugin_name: str):
        from pathlib import Path

        base = Path(str(self._cluster_root)) / "plugins" / str(plugin_name) / "instances"
        used: dict[str, set[int]] = {"game": set(), "rcon": set()}
        if not base.exists() or not base.is_dir():
            return used

        for entry in base.iterdir():
            if not entry.is_dir():
                continue
            config_path = resolve_instance_config_path(str(self._cluster_root), str(plugin_name), str(entry.name))
            if not config_path.exists():
                continue
            try:
                config = load_instance_config(str(self._cluster_root), str(plugin_name), str(entry.name))
            except Exception:
                continue

            ports = config.get("ports") if isinstance(config.get("ports"), list) else []
            game_port = self._candidate_port(ports, name="game", proto="udp")
            rcon_port = self._candidate_port(ports, name="rcon", proto="tcp")

            if game_port is None:
                try:
                    game_port = int(config.get("game_port") or 0)
                except Exception:
                    game_port = None
            if rcon_port is None:
                try:
                    rcon_port = int(config.get("rcon_port") or 0)
                except Exception:
                    rcon_port = None

            if isinstance(game_port, int) and 1 <= game_port <= 65535:
                used["game"].add(int(game_port))
            if isinstance(rcon_port, int) and 1 <= rcon_port <= 65535:
                used["rcon"].add(int(rcon_port))

        return used

    def _allocate_next_ports(self, plugin_name: str):
        starts = self._port_policy_starts(plugin_name)
        used = self._used_managed_ports(plugin_name)

        offset = 0
        while True:
            game_port = int(starts["game_port"]) + (offset * 2)
            rcon_port = int(starts["rcon_port"]) + offset
            if game_port > 65535 or rcon_port > 65535:
                return {"status": "error", "message": "No available port pair in configured policy range"}
            if game_port not in used["game"] and rcon_port not in used["rcon"]:
                return {
                    "status": "success",
                    "data": {
                        "game_port": int(game_port),
                        "rcon_port": int(rcon_port),
                    },
                }
            offset += 1

    def _candidate_ports_are_available(self, plugin_name: str, game_port: int, rcon_port: int) -> bool:
        used = self._used_managed_ports(plugin_name)
        return int(game_port) not in used["game"] and int(rcon_port) not in used["rcon"]

    def _next_available_instance_id(self, plugin_name: str) -> str:
        from pathlib import Path

        base = Path(str(self._cluster_root)) / "plugins" / str(plugin_name) / "instances"
        used = set()
        if base.exists() and base.is_dir():
            for entry in base.iterdir():
                if not entry.is_dir():
                    continue
                try:
                    value = int(str(entry.name))
                except Exception:
                    continue
                if value > 0:
                    used.add(value)

        candidate = 1
        while candidate in used:
            candidate += 1
        return str(candidate)

    @staticmethod
    def _candidate_port(ports, *, name: str, proto: str):
        if not isinstance(ports, list):
            return None
        for item in ports:
            if not isinstance(item, dict):
                continue
            if str(item.get("name") or "").strip().lower() != str(name).strip().lower():
                continue
            if str(item.get("proto") or "").strip().lower() != str(proto).strip().lower():
                continue
            try:
                value = int(item.get("port") or 0)
            except Exception:
                continue
            if 1 <= value <= 65535:
                return value
        return None

    def allocate_instance_ports(self, plugin_name):
        if not self._cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}
        return self._allocate_next_ports(str(plugin_name))

    def _load_instance_config_data(self, plugin_name: str, instance_id: str) -> dict:
        import json

        path = resolve_instance_config_path(str(self._cluster_root), str(plugin_name), str(instance_id))
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _pending_ini_sync_fields(self, plugin_name: str, instance_id: str) -> list[str]:
        data = self._load_instance_config_data(plugin_name, instance_id)
        raw = data.get("_pending_ini_sync_fields")
        if not isinstance(raw, list):
            return []
        return [str(item).strip() for item in raw if str(item).strip()]

    def suggest_next_instance_id(self, plugin_name):
        if not self._cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}
        return {"status": "success", "data": {"instance_id": self._next_available_instance_id(str(plugin_name))}}

    def sync_instance_ini_fields(self, plugin_name: str, instance_id: str, field_names):
        plugin_name = str(plugin_name)
        instance_id = str(instance_id)
        fields = [str(item).strip() for item in list(field_names or []) if str(item).strip()]
        if not fields:
            return {"status": "success", "data": {"ok": True, "warnings": [], "errors": []}}
        if self._runtime_running(plugin_name, instance_id):
            current = set(self._pending_ini_sync_fields(plugin_name, instance_id))
            for item in fields:
                current.add(item)
            self._merge_instance_config_fields(
                plugin_name,
                instance_id,
                {"_pending_ini_sync_fields": sorted(current)},
            )
            return {
                "status": "success",
                "data": {
                    "ok": True,
                    "warnings": ["INI sync deferred until the server is fully stopped."],
                    "errors": [],
                    "deferred": True,
                },
            }
        response = self.send_action(
            plugin_name,
            "sync_ini_fields",
            {"instance_id": instance_id, "fields": fields},
        )
        if self._resp_ok(response):
            remaining = set(self._pending_ini_sync_fields(plugin_name, instance_id))
            for item in fields:
                remaining.discard(item)
            payload: dict[str, object] = {"_pending_ini_sync_fields": sorted(remaining)} if remaining else {"_pending_ini_sync_fields": None}
            self._merge_instance_config_fields(plugin_name, instance_id, payload)
        return response

    def apply_pending_ini_sync_fields(self, plugin_name: str, instance_id: str) -> dict:
        fields = self._pending_ini_sync_fields(str(plugin_name), str(instance_id))
        if not fields:
            return {"status": "success", "data": {"ok": True, "warnings": [], "errors": []}}
        return self.sync_instance_ini_fields(str(plugin_name), str(instance_id), fields)

    def clear_instance_config_fields(self, plugin_name: str, instance_id: str, field_names) -> dict:
        fields = {
            str(item).strip(): None
            for item in list(field_names or [])
            if str(item).strip()
        }
        if not fields:
            return {"status": "success", "data": {"ok": True, "updated_fields": []}}
        return self._merge_instance_config_fields(plugin_name, instance_id, fields)
    def _merge_instance_config_fields(self, plugin_name: str, instance_id: str, fields: dict):
        import json
        import os
        import tempfile

        path = instance_config_path(str(self._cluster_root), str(plugin_name), str(instance_id))

        current = {}
        if path.exists():
            try:
                current = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception as e:
                return {"status": "error", "message": f"Failed to parse config: {e}"}
            if not isinstance(current, dict):
                return {"status": "error", "message": f"Config must be a JSON object: {path}"}

        for key, value in dict(fields or {}).items():
            ks = str(key)
            if value is None:
                current.pop(ks, None)
            else:
                current[ks] = value

        if "schema_version" not in current:
            current["schema_version"] = 1

        payload = json.dumps(current, indent=2, sort_keys=True) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)

        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, path)
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass

        legacy_path = legacy_instance_config_path(str(self._cluster_root), str(plugin_name), str(instance_id))
        if legacy_path != path and legacy_path.exists():
            legacy_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=legacy_path.name + ".", dir=str(legacy_path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(payload)
                os.replace(tmp, legacy_path)
            finally:
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except OSError:
                    pass

        return {
            "status": "success",
            "data": {
                "path": str(path),
                "updated_fields": sorted([str(k) for k in dict(fields or {}).keys()]),
            },
        }

    def import_server(self, plugin_name, candidate):
        if not self._cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}

        plugin_name = str(plugin_name)
        if not isinstance(candidate, dict):
            return {"status": "error", "message": "candidate must be a dict"}
        if bool(candidate.get("managed_match")):
            return {"status": "error", "message": "Candidate already matches a managed instance"}

        install_root = str(candidate.get("install_path") or "").strip()
        map_name = str(candidate.get("detected_map") or "").strip()
        if not install_root:
            return {"status": "error", "message": "Candidate install_path is required"}
        if not map_name:
            return {"status": "error", "message": "Candidate detected_map is required"}

        instance_id = self._next_available_instance_id(plugin_name)
        candidate_ports = candidate.get("ports") if isinstance(candidate.get("ports"), list) else []
        candidate_ini_fields = candidate.get("ini_fields") if isinstance(candidate.get("ini_fields"), dict) else {}
        try:
            defaults = load_plugin_defaults(str(self._cluster_root), plugin_name)
        except PluginConfigError:
            defaults = {"mods": [], "passive_mods": []}
        plugin_mods = {str(item).strip() for item in list(defaults.get("mods") or []) if str(item).strip()}
        plugin_passive_mods = {str(item).strip() for item in list(defaults.get("passive_mods") or []) if str(item).strip()}
        imported_mods = [
            str(item).strip()
            for item in list(candidate_ini_fields.get("mods") or [])
            if str(item).strip() and str(item).strip() not in plugin_mods
        ]
        imported_passive_mods = [
            str(item).strip()
            for item in list(candidate_ini_fields.get("passive_mods") or [])
            if str(item).strip() and str(item).strip() not in plugin_passive_mods
        ]
        candidate_ini_fields = dict(candidate_ini_fields)
        if "mods" in candidate_ini_fields:
            candidate_ini_fields["mods"] = imported_mods
        if "passive_mods" in candidate_ini_fields:
            candidate_ini_fields["passive_mods"] = imported_passive_mods
        game_port = self._candidate_port(candidate_ports, name="game", proto="udp")
        rcon_port = self._candidate_port(candidate_ports, name="rcon", proto="tcp")
        if (
            game_port is None
            or rcon_port is None
            or not self._candidate_ports_are_available(plugin_name, int(game_port), int(rcon_port))
        ):
            allocated = self._allocate_next_ports(plugin_name)
            if allocated.get("status") != "success":
                return allocated
            allocated_data = allocated.get("data", {}) if isinstance(allocated.get("data"), dict) else {}
            game_port = int(allocated_data.get("game_port"))
            rcon_port = int(allocated_data.get("rcon_port"))

        self._state_manager.ensure_instance_exists(plugin_name, instance_id)

        from core.instance_layout import ensure_instance_layout
        snapshot = ensure_instance_layout(str(self._cluster_root), plugin_name, instance_id)

        configured = self.configure_instance_config(
            plugin_name=plugin_name,
            instance_id=instance_id,
            map_name=map_name,
            game_port=int(game_port),
            rcon_port=int(rcon_port),
            mods=[],
            passive_mods=[],
            map_mod=None,
        )
        if configured.get("status") != "success":
            return configured

        merged = self._merge_instance_config_fields(
            plugin_name,
            instance_id,
            {
                "install_root": install_root,
                "game_port": int(game_port),
                "rcon_port": int(rcon_port),
                "admin_password": str(defaults.get("admin_password") or "").strip() or candidate_ini_fields.get("admin_password"),
                "rcon_enabled": bool(defaults.get("rcon_enabled")) if "rcon_enabled" in defaults else candidate_ini_fields.get("rcon_enabled"),
                **{
                    str(key): value
                    for key, value in candidate_ini_fields.items()
                    if str(key) not in {"map", "game_port", "rcon_port", "admin_password", "rcon_enabled"}
                },
            },
        )
        if merged.get("status") != "success":
            return merged
        from core.instance_layout import write_instance_install_status
        write_instance_install_status(str(self._cluster_root), plugin_name, instance_id, "INSTALLED")
        self._mark_instance_readiness_dirty(plugin_name, instance_id)

        return {
            "status": "success",
            "data": {
                "plugin_name": plugin_name,
                "instance_id": instance_id,
                "snapshot": snapshot,
                "instance_config_path": merged.get("data", {}).get("path"),
                "detected_map": map_name,
                "install_root": install_root,
                "game_port": int(game_port),
                "rcon_port": int(rcon_port),
            },
        }

    def configure_instance_config(
            self,
            *,
            plugin_name: str,
            instance_id: str,
            map_name: str,
            game_port: int,
            rcon_port: int,
            mods,
            passive_mods,
            map_mod=None,
    ):
        if not self._cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}

        plugin_name = str(plugin_name)
        instance_id = str(instance_id)

        # Plugin declares port specs (Core does not synthesize).
        port_specs = None
        try:
            requested = [int(game_port), int(rcon_port)]
            resp = self.send_action(plugin_name, "get_port_specs", {"requested_ports": requested})
            if isinstance(resp, dict) and resp.get("status") == "success":
                data = resp.get("data") or {}
                if isinstance(data, dict) and isinstance(data.get("ports"), list):
                    port_specs = data.get("ports")
        except Exception:
            port_specs = None

        if port_specs is None:
            return {
                "status": "error",
                "message": "Plugin did not declare port specs (get_port_specs unavailable or invalid response)",
            }

        # Port check MUST happen before any file writes.
        port_check = check_ports_availability(port_specs)
        if not port_check.get("ok"):
            return {"status": "error", "message": "Port availability check failed", "data": port_check}

        # Load defaults (missing file is ok; treated as empty defaults)
        try:
            defaults = load_plugin_defaults(self._cluster_root, plugin_name)
        except PluginConfigError as e:
            return {"status": "error", "message": str(e)}

        # Validate + compute effective merged mods
        try:
            effective = compute_effective_mods(
                plugin_defaults_mods=defaults["mods"],
                plugin_defaults_passive_mods=defaults["passive_mods"],
                instance_mods=list(mods or []),
                instance_passive_mods=list(passive_mods or []),
                map_mod=map_mod,
            )
        except PluginConfigError as e:
            return {"status": "error", "message": str(e)}

        # Ensure instance layout exists (ports already cleared).
        from core.instance_layout import ensure_instance_layout
        ensure_instance_layout(self._cluster_root, plugin_name, instance_id)

        # Create defaults file if missing (safe after port check).
        defaults_path, created_defaults = ensure_plugin_defaults_file(self._cluster_root, plugin_name)

        # Write instance config atomically.
        try:
            inst_path = write_instance_config_atomic(
                self._cluster_root,
                plugin_name,
                instance_id,
                map_name=map_name,
                map_mod=map_mod,
                mods=list(mods or []),
                passive_mods=list(passive_mods or []),
                ports=port_specs,
            )
        except PluginConfigError as e:
            return {"status": "error", "message": str(e)}

        return {
            "status": "success",
            "data": {
                "plugin_name": plugin_name,
                "instance_id": instance_id,
                "defaults_path": str(defaults_path),
                "defaults_created": bool(created_defaults),
                "instance_config_path": str(inst_path),
                "effective": effective,
                "ports": port_specs,
                "port_check": port_check,
            },
        }

    def show_instance_config(self, *, plugin_name: str, instance_id: str):
        if not self._cluster_root:
            return {"status": "error", "message": "Cluster root not configured"}

        plugin_name = str(plugin_name)
        instance_id = str(instance_id)

        try:
            defaults = load_plugin_defaults(self._cluster_root, plugin_name)
        except PluginConfigError as e:
            return {"status": "error", "message": str(e)}

        try:
            inst = load_instance_config(self._cluster_root, plugin_name, instance_id)
        except PluginConfigError as e:
            return {"status": "error", "message": str(e)}

        try:
            effective = compute_effective_mods(
                plugin_defaults_mods=defaults["mods"],
                plugin_defaults_passive_mods=defaults["passive_mods"],
                instance_mods=inst["mods"],
                instance_passive_mods=inst["passive_mods"],
                map_mod=inst.get("map_mod"),
            )
        except PluginConfigError as e:
            return {"status": "error", "message": str(e)}

        return {
            "status": "success",
            "data": {
                "plugin_defaults": defaults,
                "instance_config": inst,
                "effective": effective,
                "ports": inst.get("ports") or [],
            },
        }




















