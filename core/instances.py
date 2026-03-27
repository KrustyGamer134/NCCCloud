from __future__ import annotations

import os
from typing import Callable, Optional


_PLUGIN_ROOT_RESOLVER: Optional[Callable[[], str]] = None


def set_plugin_root_resolver(resolver: Optional[Callable[[], str]]) -> None:
    global _PLUGIN_ROOT_RESOLVER
    _PLUGIN_ROOT_RESOLVER = resolver


def plugin_root(default_root: str) -> str:
    if callable(_PLUGIN_ROOT_RESOLVER):
        resolved = _PLUGIN_ROOT_RESOLVER()
        if resolved:
            return str(resolved)
    return os.path.abspath(str(default_root))


def instance_root(default_root: str, instance_id: str) -> str:
    return instance_path(default_root, instance_id)


def instance_path(default_root: str, instance_id: str, *parts: str) -> str:
    return os.path.join(plugin_root(default_root), "instances", str(instance_id), *[str(part) for part in parts])


def instance_config_dir(default_root: str, instance_id: str) -> str:
    return instance_path(default_root, instance_id, "config")


def instance_data_dir(default_root: str, instance_id: str) -> str:
    return instance_path(default_root, instance_id, "data")


def instance_logs_dir(default_root: str, instance_id: str) -> str:
    return instance_path(default_root, instance_id, "logs")


def instance_install_dir(default_root: str, instance_id: str) -> str:
    return instance_data_dir(default_root, instance_id)
