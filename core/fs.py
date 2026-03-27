from __future__ import annotations

import os
import tempfile


def check_directory_ready(path: str, *, temp_prefix: str = "fs_check_", temp_suffix: str = ".tmp"):
    if not os.path.exists(path):
        return False, "missing"
    if not os.path.isdir(path):
        return False, "not_directory"
    try:
        fd, tmp = tempfile.mkstemp(prefix=temp_prefix, suffix=temp_suffix, dir=path)
        os.close(fd)
        os.unlink(tmp)
        return True, "ready"
    except Exception as exc:
        return False, exc
