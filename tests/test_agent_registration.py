import asyncio
import importlib.util
import types
from pathlib import Path


_MODULE_PATH = Path(__file__).resolve().parents[1] / "ncc-agent" / "agent_core" / "registration.py"
_SPEC = importlib.util.spec_from_file_location("ncc_agent_registration", _MODULE_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC is not None and _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)


class _FakeResponse:
    status_code = 201

    def json(self):
        return {"agent_id": "agent-1", "api_key": "permanent-key"}


class _FakeClient:
    def __init__(self, recorder):
        self._recorder = recorder

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json, headers):
        self._recorder.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse()


def test_ensure_registered_uses_bootstrap_api_key(monkeypatch):
    calls = []
    saved = []
    settings = types.SimpleNamespace(
        agent_state_file="agent_state.json",
        backend_http_url="http://localhost:8000",
        bootstrap_api_key="bootstrap-secret",
        api_key="wrong-agent-key",
        tenant_id="tenant-1",
    )

    monkeypatch.setattr(_MODULE, "load_agent_state", lambda _settings: None)
    monkeypatch.setattr(_MODULE, "_save_agent_state", lambda _settings, agent_id, api_key: saved.append((agent_id, api_key)))
    monkeypatch.setattr(_MODULE.httpx, "AsyncClient", lambda timeout: _FakeClient(calls))

    agent_id, api_key = asyncio.run(_MODULE.ensure_registered(settings))

    assert (agent_id, api_key) == ("agent-1", "permanent-key")
    assert saved == [("agent-1", "permanent-key")]
    assert calls[0]["headers"]["Authorization"] == "Bearer bootstrap-secret"
