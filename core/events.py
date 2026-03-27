############################################################
# SECTION: Structured Event Definitions
# Purpose:
#     Canonical internal event model.
# Lifecycle Ownership:
#     Orchestrator (Core)
# Phase:
#     CG-OBSERVABILITY-1
# Constraints:
#     - In-memory only
#     - Deterministic
#     - No persistence
#     - No wall-clock time
############################################################

EVENT_INSTANCE_STARTED = "instance_started"
EVENT_INSTANCE_STOPPED = "instance_stopped"
EVENT_INSTANCE_RESTARTED = "instance_restarted"
EVENT_INSTANCE_DISABLED = "instance_disabled"
EVENT_INSTANCE_ENABLED = "instance_enabled"
EVENT_INSTANCE_CRASHED = "instance_crashed"
EVENT_CRASH_THRESHOLD_REACHED = "crash_threshold_reached"

EVENT_MAINTENANCE_CYCLE_STARTED = "maintenance_cycle_started"
EVENT_MAINTENANCE_CYCLE_COMPLETED = "maintenance_cycle_completed"
EVENT_MAINTENANCE_CYCLE_FAILED = "maintenance_cycle_failed"
EVENT_SCHEDULING_PAUSED = "scheduling_paused"
EVENT_SCHEDULING_RESUMED = "scheduling_resumed"

EVENT_INSTALL_STARTED = "install_started"
EVENT_INSTALL_COMPLETED = "install_completed"
EVENT_INSTALL_FAILED = "install_failed"
EVENT_INSTANCE_VERSION_ADVANCED = "instance_version_advanced"


def build_event(
    event_type,
    logical_timestamp,
    plugin_name=None,
    instance_id=None,
    payload=None,
):
    return {
        "event_type": event_type,
        "plugin_name": plugin_name,
        "instance_id": instance_id,
        "logical_timestamp": int(logical_timestamp),
        "payload": payload or {},
    }
