############################################################
# SECTION: Runtime State Manager
# Purpose:
#     Provide authoritative in-memory runtime instance state.
# Lifecycle Ownership:
#     Core
# Phase:
#     Core v1.2 - Deterministic Lifecycle
# Constraints:
#     - Must not apply crash policy
#     - Must not execute lifecycle actions
#     - Must not persist to disk
############################################################

from __future__ import annotations

from typing import Optional


class StateManager:

    ############################################################
    # SECTION: Allowed States
    # Purpose:
    #     Define valid lifecycle states.
    # Lifecycle Ownership:
    #     Core
    # Phase:
    #     Core v1.2 - Deterministic Lifecycle
    # Constraints:
    #     - State definitions only
    ############################################################

    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    RESTARTING = "RESTARTING"
    UPDATING = "UPDATING"
    DISABLED = "DISABLED"

    ############################################################
    # SECTION: Initialization
    ############################################################
    def __init__(self, state_file: Optional[str] = None):
        self._state_file = state_file
        self._state: dict[str, dict[str, dict[str, str]]] = {}

    ############################################################
    # SECTION: Instance State Access
    ############################################################

    def ensure_instance_exists(self, plugin_name, instance_id):

        if plugin_name not in self._state:
            self._state[plugin_name] = {}

        if instance_id not in self._state[plugin_name]:
            self._state[plugin_name][instance_id] = {
                "state": self.STOPPED
            }

    def get_state(self, plugin_name, instance_id):

        return (
            self._state
            .get(plugin_name, {})
            .get(instance_id, {})
            .get("state")
        )

    def set_state(self, plugin_name, instance_id, state):

        self.ensure_instance_exists(plugin_name, instance_id)
        self._state[plugin_name][instance_id]["state"] = state

    def remove_instance(self, plugin_name, instance_id):
        plugin_key = str(plugin_name)
        instance_key = str(instance_id)
        plugin_state = self._state.get(plugin_key)
        if not isinstance(plugin_state, dict):
            return
        plugin_state.pop(instance_key, None)
        if not plugin_state:
            self._state.pop(plugin_key, None)
