from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path


_MODULE_PATH = Path(__file__).resolve().parents[1] / "ncc-agent" / "agent_core" / "dispatcher.py"
_SPEC = importlib.util.spec_from_file_location("ncc_agent_dispatcher_async", _MODULE_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC is not None and _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)


class _FakeWebSocket:
    def __init__(self):
        self.messages: list[str] = []

    async def send_json(self, payload: dict) -> None:
        import json
        self.messages.append(json.dumps(payload))


class _FakeAdminAPI:
    pass


async def _run_install_dispatch(monkeypatch):
    routed = []
    threaded = []
    admin_api = _FakeAdminAPI()

    def fake_route(action, plugin_name, instance_id, payload, admin_api):
        routed.append((action, plugin_name, instance_id, payload, admin_api))
        return {"status": "success", "data": {"ok": True}}

    async def fake_to_thread(func, *args, **kwargs):
        threaded.append((func, args, kwargs))
        return func(*args, **kwargs)

    monkeypatch.setattr(_MODULE, "_route", fake_route)
    monkeypatch.setattr(_MODULE.asyncio, "to_thread", fake_to_thread)

    websocket = _FakeWebSocket()
    message = {
        "type": "command",
        "command_id": "cmd-1",
        "action": "install_server",
        "plugin_name": "ark_survival_ascended",
        "instance_id": "instance-1",
    }

    await _MODULE.dispatch_command(message, admin_api, websocket.send_json)
    return routed, threaded, websocket, admin_api


def test_dispatch_command_runs_install_server_off_loop(monkeypatch):
    routed, threaded, websocket, admin_api = asyncio.run(_run_install_dispatch(monkeypatch))

    assert len(threaded) == 1
    assert threaded[0][1][0] == "install_server"
    assert routed == [
        (
            "install_server",
            "ark_survival_ascended",
            "instance-1",
            {},
            admin_api,
        )
    ]
    assert websocket.messages and '"command_id": "cmd-1"' in websocket.messages[0]


async def _run_status_dispatch(monkeypatch):
    routed = []
    threaded = []
    admin_api = _FakeAdminAPI()

    def fake_route(action, plugin_name, instance_id, payload, admin_api):
        routed.append((action, plugin_name, instance_id, payload, admin_api))
        return {"status": "success", "data": {"state": "running"}}

    async def fake_to_thread(func, *args, **kwargs):
        threaded.append((func, args, kwargs))
        return func(*args, **kwargs)

    monkeypatch.setattr(_MODULE, "_route", fake_route)
    monkeypatch.setattr(_MODULE.asyncio, "to_thread", fake_to_thread)

    websocket = _FakeWebSocket()
    message = {
        "type": "command",
        "command_id": "cmd-2",
        "action": "get_status",
        "plugin_name": "ark_survival_ascended",
        "instance_id": "instance-2",
    }

    await _MODULE.dispatch_command(message, admin_api, websocket.send_json)
    return routed, threaded, websocket, admin_api


def test_dispatch_command_runs_reads_off_loop(monkeypatch):
    routed, threaded, websocket, admin_api = asyncio.run(_run_status_dispatch(monkeypatch))

    assert len(threaded) == 1
    assert threaded[0][1][0] == "get_status"
    assert routed == [
        (
            "get_status",
            "ark_survival_ascended",
            "instance-2",
            {},
            admin_api,
        )
    ]
    assert websocket.messages and '"command_id": "cmd-2"' in websocket.messages[0]
