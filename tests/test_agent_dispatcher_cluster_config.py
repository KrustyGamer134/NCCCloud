from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ncc-agent"))

from agent_core.dispatcher import _route


class _AdminAPI:
    def __init__(self):
        self.calls = []
        self.plugin_calls = []
        self.instance_calls = []

    def set_cluster_config_fields(self, fields):
        self.calls.append(dict(fields))
        return {"status": "success", "data": {"fields": dict(fields)}}

    def get_cluster_config_fields(self, fields):
        self.calls.append(list(fields or []))
        return {"status": "success", "data": {"fields": {"cluster_name": "arkSA"}}}

    def get_plugin_config_fields(self, plugin_name):
        self.plugin_calls.append(("get", plugin_name))
        return {"status": "success", "data": {"fields": {"display_name": "ARK"}}}

    def set_plugin_config_fields(self, plugin_name, fields):
        self.plugin_calls.append(("set", plugin_name, dict(fields)))
        return {"status": "success", "data": {"fields": dict(fields)}}

    def get_instance_plugin_config_fields(self, plugin_name, instance_id, fields):
        self.instance_calls.append((plugin_name, instance_id, fields))
        return {"status": "success", "data": {"fields": {"map": "TheIsland_WP"}}}


def test_dispatcher_routes_set_cluster_config_fields_to_admin_api():
    admin_api = _AdminAPI()
    payload = {
        "fields": {
            "gameservers_root": r"D:\Ark\BriansPlayground",
            "steamcmd_root": r"D:\Ark\SteamCMD",
            "cluster_name": "arkSA",
        }
    }

    result = _route("set_cluster_config_fields", "", "", payload, admin_api)

    assert admin_api.calls == [payload["fields"]]
    assert result["status"] == "success"


def test_dispatcher_routes_get_cluster_config_fields_to_admin_api():
    admin_api = _AdminAPI()

    result = _route(
        "get_cluster_config_fields",
        "",
        "",
        {"fields": ["cluster_name"]},
        admin_api,
    )

    assert admin_api.calls == [["cluster_name"]]
    assert result["data"]["fields"]["cluster_name"] == "arkSA"


def test_dispatcher_routes_plugin_config_field_actions_to_admin_api():
    admin_api = _AdminAPI()

    get_result = _route("get_plugin_config_fields", "ark", "", {}, admin_api)
    set_result = _route(
        "set_plugin_config_fields",
        "ark",
        "",
        {"fields": {"display_name": "ARK: Survival Ascended"}},
        admin_api,
    )

    assert admin_api.plugin_calls == [
        ("get", "ark"),
        ("set", "ark", {"display_name": "ARK: Survival Ascended"}),
    ]
    assert get_result["data"]["fields"]["display_name"] == "ARK"
    assert set_result["data"]["fields"]["display_name"] == "ARK: Survival Ascended"


def test_dispatcher_routes_get_instance_plugin_config_fields_to_admin_api():
    admin_api = _AdminAPI()

    result = _route(
        "get_instance_plugin_config_fields",
        "ark",
        "instance-123",
        {"fields": ["map"]},
        admin_api,
    )

    assert admin_api.instance_calls == [("ark", "instance-123", ["map"])]
    assert result["data"]["fields"]["map"] == "TheIsland_WP"
