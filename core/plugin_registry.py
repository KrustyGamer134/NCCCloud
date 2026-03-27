############################################################
# SECTION: Plugin Registry
# Purpose:
#     Discover, load, and store plugin handlers.
# Lifecycle Ownership:
#     Core
# Phase:
#     Core v1.2 - Deterministic Lifecycle
# Constraints:
#     - Must not enforce lifecycle policy
#     - Must not modify instance state
#     - Must not apply crash policy
############################################################

import os
import json


def _load_optional_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


class PluginRegistry:

    ############################################################
    # SECTION: Initialization
    # Purpose:
    #     Store plugin directory and internal registry map.
    # Lifecycle Ownership:
    #     Core
    # Phase:
    #     Core v1.2 - Deterministic Lifecycle
    # Constraints:
    #     - Registry only
    #     - No lifecycle authority
    ############################################################
    def __init__(self, plugin_dir="plugins", cluster_root=None):
        self._plugin_dir = plugin_dir
        self._cluster_root = cluster_root
        self._plugins = {}   # name -> { handler, metadata }

    ############################################################
    # SECTION: Public Registry API
    # Purpose:
    #     Load, retrieve, and list registered plugins.
    # Lifecycle Ownership:
    #     Core
    # Phase:
    #     Core v1.2 - Deterministic Lifecycle
    # Constraints:
    #     - Must not enforce lifecycle transitions
    #     - Must not apply crash logic
    ############################################################

    def load_all(self):
        if not os.path.isdir(self._plugin_dir):
            return
        for folder in os.listdir(self._plugin_dir):
            plugin_path = os.path.join(self._plugin_dir, folder)

            if os.path.isdir(plugin_path):
                self._load_plugin(plugin_path)

    def get(self, name):
        return self._plugins.get(name)

    def list_all(self):
        return list(self._plugins.keys())

    def register_from_json(self, name: str, plugin_json: dict, cluster_root: str = "") -> None:
        """Register a plugin from a JSON dict (e.g. sourced from the DB catalog).

        Used when the agent receives a command for a plugin that was not
        discovered on disk at startup.  The plugin_dir is set to an empty
        string because there is no backing filesystem directory.
        """
        if not name or not isinstance(plugin_json, dict):
            return
        from core.plugin_handler import PluginHandler
        handler = PluginHandler(plugin_json, "", cluster_root or self._cluster_root or "")
        self._plugins[name] = {
            "handler": handler,
            "metadata": plugin_json,
        }

    def get_metadata(self, name):
        plugin = self._plugins.get(name)
        if not isinstance(plugin, dict):
            return {}
        metadata = plugin.get("metadata")
        return dict(metadata) if isinstance(metadata, dict) else {}

    ############################################################
    # SECTION: Plugin Loading Implementation
    # Purpose:
    #     Load plugin metadata and create PluginHandler.
    # Lifecycle Ownership:
    #     Core
    # Phase:
    #     Core v1.2 - Deterministic Lifecycle
    # Constraints:
    #     - Must not enforce lifecycle transitions
    #     - Must not apply crash thresholds
    ############################################################

    def _load_plugin(self, plugin_path):

        plugin_json_path = os.path.join(plugin_path, "plugin.json")

        if not os.path.exists(plugin_json_path):
            print(f"Skipping {plugin_path}: no plugin.json")
            return

        try:
            with open(plugin_json_path, "r", encoding="utf-8-sig") as f:
                metadata = json.load(f)
        except Exception:
            print(f"Skipping {plugin_path}: invalid plugin.json")
            return

        if not isinstance(metadata, dict):
            print(f"Skipping {plugin_path}: invalid plugin metadata")
            return

        capabilities = _load_optional_json(os.path.join(plugin_path, "capabilities.json"))
        if capabilities is not None:
            metadata["capabilities"] = capabilities

        name = metadata.get("name")

        if not name:
            print(f"Invalid plugin metadata in {plugin_path}")
            return

        print(f"Loading plugin: {name}")

        from core.plugin_handler import PluginHandler
        handler = PluginHandler(metadata, plugin_path, self._cluster_root or "")
        self._plugins[name] = {
            "handler": handler,
            "metadata": metadata,
        }
