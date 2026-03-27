from __future__ import annotations

from pathlib import Path
import json
import zipfile

from core.instance_layout import get_instance_root
from core.backup import SAVEDARKS_REL


def _make_zip(path: Path, entries: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def test_restore_refuses_when_not_stopped(tmp_path: Path):
    from core.admin_api import AdminAPI

    class FakeState:
        STOPPED = "STOPPED"
        RUNNING = "RUNNING"

        def ensure_instance_exists(self, *_a, **_kw):
            return None

        def get_state(self, *_a, **_kw):
            return self.RUNNING

        DISABLED = "DISABLED"

    class FakeOrch:
        def __init__(self):
            self._state_manager = FakeState()
            self._cluster_root = str(tmp_path)

        def get_instance_state(self, plugin_name, instance_id):
            self._state_manager.ensure_instance_exists(plugin_name, instance_id)
            return self._state_manager.get_state(plugin_name, instance_id)

        def _emit_event(self, *_a, **_kw):
            return None

    api = AdminAPI(FakeOrch())
    r = api.restore_instance("ark", "1", str(tmp_path / "backups"), str(tmp_path / "x.zip"), mode="world")
    assert r["status"] == "error"
    assert "STOPPED" in r["message"]


def test_restore_blocks_traversal(tmp_path: Path):
    from core.admin_api import AdminAPI

    class FakeState:
        STOPPED = "STOPPED"
        DISABLED = "DISABLED"

        def ensure_instance_exists(self, *_a, **_kw):
            return None

        def get_state(self, *_a, **_kw):
            return self.STOPPED

    class FakeOrch:
        def __init__(self):
            self._state_manager = FakeState()
            self._cluster_root = str(tmp_path)

        def get_instance_state(self, plugin_name, instance_id):
            self._state_manager.ensure_instance_exists(plugin_name, instance_id)
            return self._state_manager.get_state(plugin_name, instance_id)

        def _emit_event(self, *_a, **_kw):
            return None

    api = AdminAPI(FakeOrch())

    backup_root = tmp_path / "B"
    zip_path = backup_root / "ark" / "1" / "b.zip"
    _make_zip(zip_path, {"../evil.ark": b"x"})

    r = api.restore_instance("ark", "1", str(backup_root), str(zip_path), files=["../evil.ark"])
    assert r["status"] == "error"
    assert "Unsafe" in r["message"] or "disallowed" in r["message"]


def test_restore_mode_world_extracts_only_ark(tmp_path: Path):
    from core.admin_api import AdminAPI

    class FakeState:
        STOPPED = "STOPPED"
        DISABLED = "DISABLED"

        def ensure_instance_exists(self, *_a, **_kw):
            return None

        def get_state(self, *_a, **_kw):
            return self.STOPPED

    class FakeOrch:
        def __init__(self):
            self._state_manager = FakeState()
            self._cluster_root = str(tmp_path)

        def get_instance_state(self, plugin_name, instance_id):
            self._state_manager.ensure_instance_exists(plugin_name, instance_id)
            return self._state_manager.get_state(plugin_name, instance_id)

        def _emit_event(self, *_a, **_kw):
            return None

    api = AdminAPI(FakeOrch())

    backup_root = tmp_path / "B"
    zip_path = backup_root / "ark" / "1" / "b.zip"
    _make_zip(
        zip_path,
        {
            "TheIsland_WP.ark": b"world",
            "123.arkprofile": b"profile",
            "t.arktribe": b"tribe",
        },
    )

    r = api.restore_instance("ark", "1", str(backup_root), str(zip_path), mode="world")
    assert r["status"] == "success"
    assert r["data"]["files_restored_count"] == 1

    instance_root = get_instance_root(str(tmp_path), "ark", "1")
    target_dir = instance_root / SAVEDARKS_REL
    assert (target_dir / "TheIsland_WP.ark").exists()
    assert not (target_dir / "123.arkprofile").exists()
    assert not (target_dir / "t.arktribe").exists()


def test_restore_player_name_uses_index(tmp_path: Path):
    from core.admin_api import AdminAPI

    class FakeState:
        STOPPED = "STOPPED"
        DISABLED = "DISABLED"

        def ensure_instance_exists(self, *_a, **_kw):
            return None

        def get_state(self, *_a, **_kw):
            return self.STOPPED

    class FakeOrch:
        def __init__(self):
            self._state_manager = FakeState()
            self._cluster_root = str(tmp_path)

        def get_instance_state(self, plugin_name, instance_id):
            self._state_manager.ensure_instance_exists(plugin_name, instance_id)
            return self._state_manager.get_state(plugin_name, instance_id)

        def _emit_event(self, *_a, **_kw):
            return None

    api = AdminAPI(FakeOrch())

    backup_root = tmp_path / "B"
    inst_dir = backup_root / "ark" / "1"
    inst_dir.mkdir(parents=True, exist_ok=True)

    # player_index.json
    (inst_dir / "player_index.json").write_text(
        json.dumps(
            {"schema_version": 1, "players": [{"playerID": "76561198012345678", "name": "Krusty"}]},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    zip_path = inst_dir / "b.zip"
    _make_zip(zip_path, {"76561198012345678.arkprofile": b"profiledata"})

    r = api.restore_instance("ark", "1", str(backup_root), str(zip_path), player_name="Krusty")
    assert r["status"] == "success"
    assert r["data"]["files_restored_count"] == 1

    instance_root = get_instance_root(str(tmp_path), "ark", "1")
    target_dir = instance_root / SAVEDARKS_REL
    out = target_dir / "76561198012345678.arkprofile"
    assert out.exists()
    assert out.read_bytes() == b"profiledata"