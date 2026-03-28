from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ncc_app:changeme@localhost:5432/ncc_test")
os.environ.setdefault("CLERK_JWKS_URL", "https://example.test/.well-known/jwks.json")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("NCC_CORE_PATH", "E:\\NCCCloud")

from api.agent_ws import _COMMAND_TIMEOUT, _INSTALL_SERVER_TIMEOUT, _command_timeout_for


def test_command_timeout_for_install_server_uses_extended_timeout():
    assert _command_timeout_for({"action": "install_server"}) == float(_INSTALL_SERVER_TIMEOUT)


def test_command_timeout_for_non_install_commands_uses_default_timeout():
    assert _command_timeout_for({"action": "start"}) == float(_COMMAND_TIMEOUT)
    assert _command_timeout_for({}) == float(_COMMAND_TIMEOUT)
