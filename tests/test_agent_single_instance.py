from __future__ import annotations

import importlib.util
from pathlib import Path


_MODULE_PATH = Path(__file__).resolve().parents[1] / "ncc-agent" / "agent_core" / "single_instance.py"
_SPEC = importlib.util.spec_from_file_location("ncc_agent_single_instance", _MODULE_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC is not None and _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)


class _FakeKernel32:
    def __init__(self, errors):
        self._errors = list(errors)
        self.closed = []
        self.created = []
        self._last_error = 0

    def CreateMutexW(self, _security, _initial_owner, name):
        self.created.append(name)
        self._last_error = self._errors.pop(0)
        return len(self.created)

    def GetLastError(self):
        return self._last_error

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True


def test_acquire_single_instance_first_process_wins(monkeypatch):
    monkeypatch.setattr(_MODULE.os, "name", "nt")
    monkeypatch.setattr(_MODULE, "_mutex_handle", None)
    kernel32 = _FakeKernel32([0])

    ok = _MODULE.acquire_single_instance(
        cluster_root=r"D:\Ark",
        entrypoint_name="main.py",
        kernel32=kernel32,
    )

    assert ok is True
    assert kernel32.closed == []
    assert kernel32.created and kernel32.created[0].startswith("Local\\NCCAgent_")


def test_acquire_single_instance_duplicate_process_exits(monkeypatch):
    monkeypatch.setattr(_MODULE.os, "name", "nt")
    monkeypatch.setattr(_MODULE, "_mutex_handle", None)
    kernel32 = _FakeKernel32([_MODULE.ERROR_ALREADY_EXISTS])

    ok = _MODULE.acquire_single_instance(
        cluster_root=r"D:\Ark",
        entrypoint_name="main.py",
        kernel32=kernel32,
    )

    assert ok is False
    assert kernel32.closed == [1]
