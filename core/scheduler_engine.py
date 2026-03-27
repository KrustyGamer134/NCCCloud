############################################################
# SECTION: Scheduler Engine Definition
# Purpose:
# Control plane for deterministic maintenance cycle orchestration.
# Lifecycle Ownership:
# Orchestrator (Core)
# Phase:
# Scheduled Restart Architecture - Phase 4A (Control Plane)
# Constraints:
# - Manual trigger only.
# - No persistence.
# - No background threads.
############################################################

class SchedulerEngine:

    ############################################################
    # SECTION: Initialization
    # Purpose:
    # Initialize maintenance cycle state and configuration.
    # Lifecycle Ownership:
    # Orchestrator (Core)
    # Phase:
    # Scheduled Restart Architecture - Phase 4A (Control Plane)
    # Constraints:
    # - Manual trigger only.
    # - No persistence.
    # - No background threads.
    ############################################################
    def __init__(
        self,
        orchestrator,
        escalation_threshold=2,
        buffer_seconds=10,
        watchdog_timeout=1800
    ):
        self._orchestrator = orchestrator

        self._maintenance_active = False
        self._cycle_failed = False
        self._scheduling_paused = False

        self._current_plugin = None
        self._plugin_queue = []

        self._failed_plugin_windows = 0
        self.escalation_threshold = escalation_threshold

        self.buffer_seconds = buffer_seconds
        self.watchdog_timeout = watchdog_timeout

        self._window_start_time = None
        self._last_plugin_activity_time = None

        self._plugin_last_window_duration = {}
        self._scheduled_next_window_time = None

    ############################################################
    # SECTION: Begin Maintenance Cycle
    # Purpose:
    # Initialize and start a maintenance cycle.
    # Lifecycle Ownership:
    # Orchestrator (Core)
    # Phase:
    # Scheduled Restart Architecture - Phase 4A (Control Plane)
    # Constraints:
    # - Manual trigger only.
    # - No persistence.
    # - No background threads.
    ############################################################
    def begin_maintenance_cycle(self, plugin_order, current_time):

        if self._scheduling_paused:
            return False

        if self._maintenance_active:
            return False

        self._maintenance_active = True
        self._cycle_failed = False
        self._failed_plugin_windows = 0

        self._plugin_queue = list(plugin_order)
        self._current_plugin = None
        self._scheduled_next_window_time = None

        if not self._plugin_queue:
            self._maintenance_active = False
            return False

        self._open_next_window(current_time)
        return True

    ############################################################
    # SECTION: Resume After Failure
    # Purpose:
    # Clear pause state after escalation.
    # Lifecycle Ownership:
    # Orchestrator (Core)
    # Phase:
    # Scheduled Restart Architecture - Phase 4A (Control Plane)
    # Constraints:
    # - Manual trigger only.
    # - No persistence.
    # - No background threads.
    ############################################################
    def resume_after_failure(self):
        self._scheduling_paused = False
        self._cycle_failed = False

    ############################################################
    # SECTION: Handle Plugin Event
    # Purpose:
    # Process plugin events during maintenance window.
    # Lifecycle Ownership:
    # Orchestrator (Core)
    # Phase:
    # Scheduled Restart Architecture - Phase 4A (Control Plane)
    # Constraints:
    # - Manual trigger only.
    # - No persistence.
    # - No background threads.
    ############################################################
    def handle_plugin_event(self, plugin_name, event, current_time):

        if not self._maintenance_active:
            return

        if plugin_name != self._current_plugin:
            return

        self._last_plugin_activity_time = current_time

        event_type = event.get("event_type")

        if event_type == "window_complete":
            self._close_current_window(current_time)

    ############################################################
    # SECTION: Tick Evaluation
    # Purpose:
    # Deterministically evaluate watchdog and scheduling.
    # Lifecycle Ownership:
    # Orchestrator (Core)
    # Phase:
    # Scheduled Restart Architecture - Phase 4A (Control Plane)
    # Constraints:
    # - Manual trigger only.
    # - No persistence.
    # - No background threads.
    ############################################################
    def tick(self, current_time):

        if not self._maintenance_active:
            return

        # Watchdog enforcement
        if self._current_plugin is not None:
            if (
                current_time - self._last_plugin_activity_time
                > self.watchdog_timeout
            ):
                self._mark_window_failed(current_time)

        # Start next window if scheduled
        if (
            self._scheduled_next_window_time is not None
            and current_time >= self._scheduled_next_window_time
        ):
            self._scheduled_next_window_time = None
            self._open_next_window(current_time)

    ############################################################
    # SECTION: Open Plugin Window
    # Purpose:
    # Activate next plugin maintenance window.
    # Lifecycle Ownership:
    # Orchestrator (Core)
    # Phase:
    # Scheduled Restart Architecture - Phase 4A (Control Plane)
    # Constraints:
    # - Manual trigger only.
    # - No persistence.
    # - No background threads.
    ############################################################
    def _open_next_window(self, current_time):

        if not self._plugin_queue:
            self._complete_cycle()
            return

        self._current_plugin = self._plugin_queue.pop(0)

        self._orchestrator.reset_stability_for_plugin(
            self._current_plugin
        )

        self._orchestrator.clear_disabled_for_plugin(
            self._current_plugin
        )

        self._orchestrator.notify_plugin_window_open(
            self._current_plugin
        )

        self._window_start_time = current_time
        self._last_plugin_activity_time = current_time

    ############################################################
    # SECTION: Close Plugin Window
    # Purpose:
    # Finalize current plugin window and schedule next.
    # Lifecycle Ownership:
    # Orchestrator (Core)
    # Phase:
    # Scheduled Restart Architecture - Phase 4A (Control Plane)
    # Constraints:
    # - Manual trigger only.
    # - No persistence.
    # - No background threads.
    ############################################################
    def _close_current_window(self, current_time):

        duration = current_time - self._window_start_time
        self._plugin_last_window_duration[
            self._current_plugin
        ] = duration

        self._orchestrator.notify_plugin_window_close(
            self._current_plugin
        )

        self._current_plugin = None

        if not self._plugin_queue:
            self._complete_cycle()
            return

        self._scheduled_next_window_time = (
            current_time + self.buffer_seconds
        )

    ############################################################
    # SECTION: Mark Window Failed
    # Purpose:
    # Apply watchdog failure policy.
    # Lifecycle Ownership:
    # Orchestrator (Core)
    # Phase:
    # Scheduled Restart Architecture - Phase 4A (Control Plane)
    # Constraints:
    # - Manual trigger only.
    # - No persistence.
    # - No background threads.
    ############################################################
    def _mark_window_failed(self, current_time):

        self._failed_plugin_windows += 1

        self._orchestrator.notify_plugin_window_close(
            self._current_plugin
        )

        self._current_plugin = None

        if self._failed_plugin_windows >= self.escalation_threshold:
            self._escalate()
            return

        if not self._plugin_queue:
            self._complete_cycle()
            return

        self._scheduled_next_window_time = (
            current_time + self.buffer_seconds
        )

    ############################################################
    # SECTION: Escalation Enforcement
    # Purpose:
    # Abort cycle when failure threshold reached.
    # Lifecycle Ownership:
    # Orchestrator (Core)
    # Phase:
    # Scheduled Restart Architecture - Phase 4A (Control Plane)
    # Constraints:
    # - Manual trigger only.
    # - No persistence.
    # - No background threads.
    ############################################################
    def _escalate(self):

        self._cycle_failed = True
        self._scheduling_paused = True
        self._maintenance_active = False
        self._current_plugin = None
        self._plugin_queue = []

    ############################################################
    # SECTION: Complete Cycle
    # Purpose:
    # Finalize successful maintenance cycle.
    # Lifecycle Ownership:
    # Orchestrator (Core)
    # Phase:
    # Scheduled Restart Architecture - Phase 4A (Control Plane)
    # Constraints:
    # - Manual trigger only.
    # - No persistence.
    # - No background threads.
    ############################################################
    def _complete_cycle(self):

        self._maintenance_active = False
        self._failed_plugin_windows = 0
        self._current_plugin = None
        self._plugin_queue = []

    ############################################################
    # SECTION: Read-Only State Accessors
    # Purpose:
    # Expose immutable scheduler state through controlled API.
    # Lifecycle Ownership:
    # Orchestrator (Core)
    # Phase:
    # Scheduled Restart Architecture - Phase 4A (Control Plane)
    # Constraints:
    # - Manual trigger only.
    # - No persistence.
    # - No background threads.
    ############################################################

    def is_maintenance_active(self):
        return self._maintenance_active

    def is_maintenance_paused(self):
        return self._scheduling_paused

    def is_maintenance_failed(self):
        return self._cycle_failed

    def get_current_plugin(self):
        return self._current_plugin

    def get_failed_plugin_count(self):
        return self._failed_plugin_windows

    def get_escalation_threshold(self):
        return self.escalation_threshold

    def get_next_window_time(self):
        return self._scheduled_next_window_time

    def get_plugin_last_window_duration(self, plugin_name):
        value = self._plugin_last_window_duration.get(plugin_name)
        return None if value is None else float(value)

    _PHASE_4B_GUARD_MESSAGE = "Phase 4B not authorized in stable_l7_persist_v2"

    _PHASE_4B_FORBIDDEN_KEYS = {
        "daily",
        "weekly",
        "time_of_day",
        "cron",
        "schedule_time",
        "day_of_week",
        "days_of_week",
    }

    def apply_schedule_config(self, config):
        """
        Governance-only ingestion boundary for scheduler configuration.
        This is a no-op for Phase 4A.
        """

        if config is None:
            return

        if not isinstance(config, dict):
            raise TypeError("SchedulerEngine.apply_schedule_config expects dict or None")

        if self._contains_phase4b_fields(config):
            raise ValueError(self._PHASE_4B_GUARD_MESSAGE)

        # Phase 4A / empty config: do nothing
        return

    @classmethod
    def _contains_phase4b_fields(cls, obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and k.lower() in cls._PHASE_4B_FORBIDDEN_KEYS:
                    return True
                if cls._contains_phase4b_fields(v):
                    return True
            return False

        if isinstance(obj, list):
            for item in obj:
                if cls._contains_phase4b_fields(item):
                    return True
            return False

        return False