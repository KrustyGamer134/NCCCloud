from __future__ import annotations

import os


def read_text_lines(path: str, *, encoding: str = "utf-8", errors: str = "replace"):
    if not os.path.exists(path) or not os.path.isfile(path):
        return False, []
    try:
        with open(path, "r", encoding=encoding, errors=errors) as handle:
            return True, handle.read().splitlines()
    except Exception:
        return False, []


def tail_file_lines(path: str, last_lines: int, *, encoding: str = "utf-8", errors: str = "replace"):
    n = int(last_lines)
    if n <= 0:
        return True, []
    found, lines = read_text_lines(path, encoding=encoding, errors=errors)
    if not found:
        return False, []
    return True, (lines[-n:] if len(lines) > n else lines)
