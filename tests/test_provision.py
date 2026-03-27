from __future__ import annotations

from pathlib import Path
import json

from core.admin_api import AdminAPI
from core.instance_layout import get_instance_root


class FakeState:
    STOPPED = "STOPPED"
    DISABLED = "DISABLED"


class FakeOrch:
    def __init__(self, cluster_root: str):
        self._cluster_root = cluster_root
        self._state_manager = FakeState()
        self.called = []

    # If anything lifecycle-ish gets called, we record it.
    def __getattr__(self, name):
        def _missing(*args, **kwargs):
            self.called.append(name)
            raise AssertionError(f"Orchestrator method should not be called by provisioning: {name}")
        return _missing


def test_validate_fails_on_nonexistent_cluster_root(tmp_path: Path, monkeypatch):
    api = AdminAPI(FakeOrch(str(tmp_path)))

    # Stub PluginRegistry so validate doesn't depend on real plugins
    class FakeRegistry:
        def __init__(self, plugin_dir=None, **kwargs):
            self.plugin_dir = plugin_dir

        def load_all(self):
            return None

    import core.plugin_registry as pr
    monkeypatch.setattr(pr, "PluginRegistry", FakeRegistry)

    bad_root = tmp_path / "nope"
    r = api.validate_environment(str(bad_root))
    assert r["ok"] is False
    assert any(c["name"] == "cluster_root_exists" and c["ok"] is False for c in r["checks"])


def test_validate_passes_for_valid_root(tmp_path: Path, monkeypatch):
    api = AdminAPI(FakeOrch(str(tmp_path)))

    (tmp_path / "plugins").mkdir(parents=True, exist_ok=True)

    class FakeRegistry:
        def __init__(self, plugin_dir=None, **kwargs):
            self.plugin_dir = plugin_dir

        def load_all(self):
            return None

    import core.plugin_registry as pr
    monkeypatch.setattr(pr, "PluginRegistry", FakeRegistry)

    r = api.validate_environment(str(tmp_path))
    assert r["ok"] is True


def test_add_instance_creates_layout_and_is_idempotent(tmp_path: Path):
    api = AdminAPI(FakeOrch(str(tmp_path)))

    r1 = api.add_instance("ark", "1")
    assert r1["status"] == "success"
    assert r1["data"]["action"] == "created"

    inst_root = get_instance_root(str(tmp_path), "ark", "1")
    assert (inst_root / "config").is_dir()
    assert (inst_root / "data").is_dir()
    assert (inst_root / "logs").is_dir()
    assert (inst_root / "backups").is_dir()

    meta = inst_root / "instance.json"
    assert meta.exists()
    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert payload["plugin_name"] == "ark"
    assert payload["instance_id"] == "1"
    assert payload["schema_version"] == 1
    assert payload["install_status"] == "NOT_INSTALLED"

    r2 = api.add_instance("ark", "1")
    assert r2["status"] == "success"
    assert r2["data"]["action"] == "already_exists"


def test_provisioning_does_not_call_orchestrator_lifecycle(tmp_path: Path, monkeypatch):
    orch = FakeOrch(str(tmp_path))
    api = AdminAPI(orch)

    # validate: stub registry
    class FakeRegistry:
        def __init__(self, plugin_dir=None, **kwargs):
            self.plugin_dir = plugin_dir

        def load_all(self):
            return None

    import core.plugin_registry as pr
    monkeypatch.setattr(pr, "PluginRegistry", FakeRegistry)

    api.validate_environment(str(tmp_path))
    api.add_instance("ark", "99")

    # If any orchestrator method was called via __getattr__, test would have failed.
    assert orch.called == []


def test_validate_warns_when_ark_test_mode_missing(tmp_path: Path, monkeypatch):
    """
    If plugins/ark exists but plugin_config.json is missing test_mode,
    validate must WARN (report-only) and strict must FAIL.
    """
    api = AdminAPI(FakeOrch(str(tmp_path)))
    (tmp_path / "plugins" / "ark").mkdir(parents=True, exist_ok=True)

    # Create plugin_config.json without test_mode
    cfg = {"schema_version": 1, "mods": [], "passive_mods": []}
    (tmp_path / "plugins" / "ark" / "plugin_config.json").write_text(json.dumps(cfg), encoding="utf-8")

    class FakeRegistry:
        def __init__(self, plugin_dir=None, **kwargs):
            self.plugin_dir = plugin_dir

        def load_all(self):
            return None

    import core.plugin_registry as pr
    monkeypatch.setattr(pr, "PluginRegistry", FakeRegistry)

    r = api.validate_environment(str(tmp_path), strict=False)
    assert r["ok"] is True
    warns = r.get("warnings") or []
    assert any(w.get("name") == "ark_test_mode_missing" for w in warns)

    r2 = api.validate_environment(str(tmp_path), strict=True)
    assert r2["ok"] is False


def test_validate_warns_when_ark_test_mode_true(tmp_path: Path, monkeypatch):
    api = AdminAPI(FakeOrch(str(tmp_path)))
    (tmp_path / "plugins" / "ark").mkdir(parents=True, exist_ok=True)

    cfg = {"schema_version": 1, "mods": [], "passive_mods": [], "test_mode": True}
    (tmp_path / "plugins" / "ark" / "plugin_config.json").write_text(json.dumps(cfg), encoding="utf-8")

    class FakeRegistry:
        def __init__(self, plugin_dir=None, **kwargs):
            self.plugin_dir = plugin_dir

        def load_all(self):
            return None

    import core.plugin_registry as pr
    monkeypatch.setattr(pr, "PluginRegistry", FakeRegistry)

    r = api.validate_environment(str(tmp_path), strict=False)
    assert r["ok"] is True
    warns = r.get("warnings") or []
    assert any(w.get("name") == "ark_test_mode_enabled" for w in warns)

    r2 = api.validate_environment(str(tmp_path), strict=True)
    assert r2["ok"] is False


def test_validate_strict_passes_when_ark_test_mode_false(tmp_path: Path, monkeypatch):
    api = AdminAPI(FakeOrch(str(tmp_path)))
    (tmp_path / "plugins" / "ark").mkdir(parents=True, exist_ok=True)

    cfg = {"schema_version": 1, "mods": [], "passive_mods": [], "test_mode": False}
    (tmp_path / "plugins" / "ark" / "plugin_config.json").write_text(json.dumps(cfg), encoding="utf-8")

    class FakeRegistry:
        def __init__(self, plugin_dir=None, **kwargs):
            self.plugin_dir = plugin_dir

        def load_all(self):
            return None

    import core.plugin_registry as pr
    monkeypatch.setattr(pr, "PluginRegistry", FakeRegistry)

    r = api.validate_environment(str(tmp_path), strict=True)
    assert r["ok"] is True
    warns = r.get("warnings") or []
    assert not any(w.get("name") in ("ark_test_mode_missing", "ark_test_mode_enabled") for w in warns)


def test_validate_does_not_write_files_for_test_mode_checks(tmp_path: Path, monkeypatch):
    """
    validate must be report-only: it must not create plugin_config.json.
    """
    api = AdminAPI(FakeOrch(str(tmp_path)))
    (tmp_path / "plugins" / "ark").mkdir(parents=True, exist_ok=True)

    cfg_path = tmp_path / "plugins" / "ark" / "plugin_config.json"
    assert not cfg_path.exists()

    class FakeRegistry:
        def __init__(self, plugin_dir=None, **kwargs):
            self.plugin_dir = plugin_dir

        def load_all(self):
            return None

    import core.plugin_registry as pr
    monkeypatch.setattr(pr, "PluginRegistry", FakeRegistry)

    r = api.validate_environment(str(tmp_path), strict=False)
    assert "warnings" in r
    assert not cfg_path.exists()