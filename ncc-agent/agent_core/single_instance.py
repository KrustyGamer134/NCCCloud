from __future__ import annotations

import ctypes
import hashlib
import os


ERROR_ALREADY_EXISTS = 183
_mutex_handle = None


def _mutex_name(*, cluster_root: str, entrypoint_name: str | None = None) -> str:
    normalized_root = os.path.normcase(os.path.abspath(str(cluster_root or "")))
    digest = hashlib.sha256(normalized_root.encode("utf-8")).hexdigest()
    return f"Local\\NCCAgent_{digest}"


def acquire_single_instance(*, cluster_root: str, entrypoint_name: str, kernel32=None) -> bool:
    global _mutex_handle

    if os.name != "nt":
        return True

    win32 = kernel32 or ctypes.windll.kernel32
    handle = win32.CreateMutexW(None, False, _mutex_name(cluster_root=cluster_root, entrypoint_name=entrypoint_name))
    if not handle:
        raise OSError("CreateMutexW failed")
    if win32.GetLastError() == ERROR_ALREADY_EXISTS:
        win32.CloseHandle(handle)
        return False
    _mutex_handle = handle
    return True
