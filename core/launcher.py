from __future__ import annotations
import os
import subprocess
from typing import List


def dedupe_preserve_order(items) -> list:
    out: List[str] = []
    seen = set()
    for x in items or []:
        s = str(x).strip()
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def compute_effective_active_mods(defaults: dict, inst: dict) -> list:
    map_mod = inst.get("map_mod")
    defaults_mods = defaults.get("mods") or []
    inst_mods = inst.get("mods") or []

    mods: List[str] = []
    if map_mod:
        mods.append(str(map_mod))
    mods.extend([str(x) for x in defaults_mods])
    mods.extend([str(x) for x in inst_mods])
    return dedupe_preserve_order(mods)


def compute_effective_passive_mods(defaults: dict, inst: dict) -> list:
    defaults_passive = defaults.get("passive_mods") or []
    inst_passive = inst.get("passive_mods") or []
    mods: List[str] = []
    mods.extend([str(x) for x in defaults_passive])
    mods.extend([str(x) for x in inst_passive])
    return dedupe_preserve_order(mods)


def server_launch_creationflags() -> int:
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def spawn_server_process(
    argv: list,
    *,
    cwd: str,
    creationflags: int = 0,
    stdout=None,
    stderr=None,
    text: bool = False,
    subprocess_module,
) -> object:
    return subprocess_module.Popen(
        argv,
        cwd=cwd,
        shell=False,
        creationflags=creationflags,
        stdout=stdout,
        stderr=stderr,
        text=text,
    )
