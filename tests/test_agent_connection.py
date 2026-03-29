import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_AGENT_ROOT = _ROOT / "ncc-agent"
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))

_MODULE_PATH = _AGENT_ROOT / "agent_core" / "connection.py"
_SPEC = importlib.util.spec_from_file_location("ncc_agent_connection", _MODULE_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC is not None and _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)


class _FakeWebSocket:
    def __init__(self, messages):
        self._messages = list(messages)
        self.sent = []

    async def recv(self):
        if self._messages:
            item = self._messages.pop(0)
            if isinstance(item, Exception):
                raise item
            return json.dumps(item)
        raise asyncio.TimeoutError()

    async def send(self, payload):
        self.sent.append(payload)


def test_message_loop_dispatches_commands_concurrently(monkeypatch):
    settings = types.SimpleNamespace(agent_id="agent-1")
    conn = _MODULE.AgentConnection(settings, admin_api=object())
    ws = _FakeWebSocket(
        [
            {"type": "command", "command_id": "cmd-1"},
            {"type": "command", "command_id": "cmd-2"},
            RuntimeError("stop"),
        ]
    )
    conn._ws = ws

    started = []
    release = None

    async def fake_dispatch(msg, _admin_api, _send_json):
        nonlocal release
        started.append(msg["command_id"])
        if release is None:
            release = asyncio.Event()
        await release.wait()

    async def run():
        task = asyncio.create_task(conn._message_loop(ws))
        while len(started) < 2:
            await asyncio.sleep(0)
        release.set()
        try:
            await task
        except RuntimeError as exc:
            assert str(exc) == "stop"
        await conn.wait_for_command_tasks()

    monkeypatch.setattr(_MODULE, "dispatch_command", fake_dispatch)

    asyncio.run(run())

    assert started == ["cmd-1", "cmd-2"]
