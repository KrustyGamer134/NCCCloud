############################################################
# SECTION: MaintenanceStateStore
# Purpose:
#     JSON persistence layer for maintenance cycle state.
# Lifecycle Ownership:
#     Orchestrator (Core)
# Phase:
#     Scheduled Restart Architecture - Phase 4B (Time Trigger)
# Constraints:
#     - No auto-run of missed schedule.
#     - Deterministic tick-driven.
#     - Persistence isolated from scheduler logic.
############################################################

import json
import os


class MaintenanceStateStore:

    def __init__(self, path="data/maintenance_state.json"):
        self._path = path
        self._state = None
        self.load_state()

    ############################################################
    # Persistence
    ############################################################

    def load_state(self):

        if not os.path.exists(self._path):
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            self._state = {
                "last_cycle_status": "NONE",
                "last_cycle_result": None,
                "last_cycle_start_time": None,
                "last_cycle_end_time": None,
                "last_successful_cycle_date": None,
                "last_skipped_cycle_date": None
            }
            self.save_state()
            return

        with open(self._path, "r") as f:
            self._state = json.load(f)

    def save_state(self):

        with open(self._path, "w") as f:
            json.dump(self._state, f, indent=4)

    ############################################################
    # Getters
    ############################################################

    def get_last_cycle_status(self):
        return self._state["last_cycle_status"]

    def get_last_cycle_result(self):
        return self._state["last_cycle_result"]

    def get_last_cycle_start_time(self):
        return self._state["last_cycle_start_time"]

    def get_last_cycle_end_time(self):
        return self._state["last_cycle_end_time"]

    def get_last_successful_cycle_date(self):
        return self._state["last_successful_cycle_date"]

    def get_last_skipped_cycle_date(self):
        return self._state["last_skipped_cycle_date"]

    ############################################################
    # Mutators
    ############################################################

    def set_cycle_started(self, start_time):

        iso = start_time.astimezone().isoformat()

        self._state["last_cycle_status"] = "IN_PROGRESS"
        self._state["last_cycle_start_time"] = iso
        self._state["last_cycle_end_time"] = None
        self._state["last_cycle_result"] = None

        self.save_state()

    def set_cycle_completed(self, end_time, result):

        iso = end_time.astimezone().isoformat()
        today = end_time.date().isoformat()

        self._state["last_cycle_status"] = "COMPLETED"
        self._state["last_cycle_end_time"] = iso
        self._state["last_cycle_result"] = result
        self._state["last_successful_cycle_date"] = today

        self.save_state()

    def set_cycle_failed(self, end_time, result):

        iso = end_time.astimezone().isoformat()

        self._state["last_cycle_status"] = "FAILED"
        self._state["last_cycle_end_time"] = iso
        self._state["last_cycle_result"] = result

        self.save_state()

    def set_cycle_aborted(self, end_time, result):

        iso = end_time.astimezone().isoformat()

        self._state["last_cycle_status"] = "ABORTED"
        self._state["last_cycle_end_time"] = iso
        self._state["last_cycle_result"] = result

        self.save_state()

    def set_skipped_date(self, date_value):

        self._state["last_skipped_cycle_date"] = date_value.isoformat()
        self.save_state()