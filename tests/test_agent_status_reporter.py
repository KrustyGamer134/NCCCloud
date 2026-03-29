import asyncio
import importlib.util
from pathlib import Path


_MODULE_PATH = Path(__file__).resolve().parents[1] / "ncc-agent" / "agent_core" / "status_reporter.py"
_SPEC = importlib.util.spec_from_file_location("ncc_agent_status_reporter", _MODULE_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC is not None and _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)


def test_status_reporter_skips_snapshot_when_disconnected(monkeypatch):
    collected = []
    sent = []

    async def fake_sleep(_seconds):
        raise RuntimeError("stop")

    def fake_get_snapshot(_admin_api):
        collected.append(True)
        return {"instances": []}

    async def fake_send_json(payload):
        sent.append(payload)

    monkeypatch.setattr(_MODULE.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(_MODULE, "_get_snapshot", fake_get_snapshot)

    try:
        asyncio.run(
            _MODULE.run_status_reporter(
                "agent-1",
                object(),
                fake_send_json,
                lambda: False,
            )
        )
    except RuntimeError as exc:
        assert str(exc) == "stop"

    assert collected == []
    assert sent == []


def test_status_reporter_collects_snapshot_off_loop_and_sends(monkeypatch):
    collected = []
    sent = []
    sleeps = 0

    async def fake_sleep(_seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps > 1:
            raise RuntimeError("stop")

    def fake_get_snapshot(_admin_api):
        collected.append(True)
        return {"instances": [{"instance_id": "1", "status": "running"}]}

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def fake_send_json(payload):
        sent.append(payload)
        raise RuntimeError("stop")

    monkeypatch.setattr(_MODULE.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(_MODULE.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(_MODULE, "_get_snapshot", fake_get_snapshot)

    try:
        asyncio.run(
            _MODULE.run_status_reporter(
                "agent-1",
                object(),
                fake_send_json,
                lambda: True,
            )
        )
    except RuntimeError as exc:
        assert str(exc) == "stop"

    assert collected == [True]
    assert sent == [
        {
            "type": "status_update",
            "agent_id": "agent-1",
            "data": {"instances": [{"instance_id": "1", "status": "running"}]},
        }
    ]
