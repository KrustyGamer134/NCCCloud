from __future__ import annotations

import os
import re


def write_pid_file(write_text_file_fn, path: str, pid: int) -> None:
    write_text_file_fn(path, f"{int(pid)}\n")


def remove_pid_file(path: str) -> None:
    try:
        if os.path.exists(path) and os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass


def read_pid_file(path: str):
    try:
        if not os.path.exists(path) or not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8-sig") as handle:
            raw = (handle.read() or "").strip()
        if not raw:
            return None
        return int(raw.splitlines()[0].strip())
    except Exception:
        return None


def tasklist_pid_running(pid: int, *, timeout_seconds: float, subprocess_module):
    try:
        cp = subprocess_module.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        out = cp.stdout or ""
        if "No tasks are running which match" in out:
            return False, None
        found = re.search(rf"\b{int(pid)}\b", out) is not None
        return bool(found), None
    except Exception as exc:
        return False, f"tasklist probe failed: {exc}"


def tasklist_first_pid(*, timeout_seconds: float, process_names=None, subprocess_module):
    try:
        cp = subprocess_module.run(
            ["tasklist"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        out = cp.stdout or ""
        targets = [str(x).strip().lower() for x in list(process_names or []) if str(x).strip()]
        for line in out.splitlines():
            text = str(line).strip()
            if not text:
                continue
            lowered = text.lower()
            if targets and not any(name in lowered for name in targets):
                continue
            match = re.search(r"\b(\d+)\b", text)
            if match:
                return int(match.group(1)), None
        return None, None
    except Exception as exc:
        return None, f"tasklist process probe failed: {exc}"
