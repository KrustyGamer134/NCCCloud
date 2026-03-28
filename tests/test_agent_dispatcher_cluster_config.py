from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ncc-agent"))

from agent_core.dispatcher import _route


class _AdminAPI:
    def __init__(self):
        self.calls = []

    def set_cluster_config_fields(self, fields):
        self.calls.append(dict(fields))
        return {"status": "success", "data": {"fields": dict(fields)}}


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
