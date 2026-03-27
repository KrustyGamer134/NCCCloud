############################################################
# SECTION: TimeScheduler
# Purpose:
#     Evaluates deterministic daily scheduled restart trigger.
# Lifecycle Ownership:
#     Orchestrator (Core)
# Phase:
#     Scheduled Restart Architecture - Phase 4B (Time Trigger)
# Constraints:
#     - No auto-run of missed schedule.
#     - Deterministic tick-driven.
#     - Persistence isolated from scheduler logic.
############################################################

from datetime import time


class TimeScheduler:

    def __init__(self, orchestrator, registry, scheduled_time: str):
        self._orchestrator = orchestrator
        self._registry = registry
        self._scheduled_time_str = scheduled_time
        self._last_trigger_date = None

    def tick(self, current_datetime):

        if not self._orchestrator.is_scheduling_enabled():
            return

        if self._orchestrator.is_maintenance_active():
            return

        if self._orchestrator.is_maintenance_paused():
            return

        hour, minute = map(int, self._scheduled_time_str.split(":"))
        scheduled_time = time(hour=hour, minute=minute)

        if current_datetime.time() < scheduled_time:
            return

        today = current_datetime.date().isoformat()

        if self._last_trigger_date == today:
            return

        last_success = self._orchestrator.get_last_successful_cycle_date()
        last_skipped = self._orchestrator.get_last_skipped_cycle_date()

        if last_success == today or last_skipped == today:
            return

        if self._orchestrator.is_maintenance_missed():
            return

        self._orchestrator._maintenance_missed = True