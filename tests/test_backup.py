from __future__ import annotations

from pathlib import Path
import json
import zipfile

from core.backup import (
    save_manifest,
    load_manifest,
    compute_delta,
    create_backup_zip,
    derive_map_name_from_savedarks,
    MANIFEST_NAME,
)


def _touch(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_manifest_delta_logic_new_vs_unchanged(tmp_path: Path):
    savedarks = tmp_path / "SavedArks"
    f1 = savedarks / "TheIsland.ark"
    f2 = savedarks / "p1.arkprofile"
    _touch(f1, b"a" * 10)
    _touch(f2, b"b" * 5)

    manifest_path = tmp_path / MANIFEST_NAME
    entries = {}
    # Save manifest with current stats of f1 only
    st1 = f1.stat()
    entries["TheIsland.ark"] = type("E", (), {"size_bytes": st1.st_size, "mtime_ns": st1.st_mtime_ns})()
    # Use real save_manifest by converting to required ManifestEntry shape via JSON roundtrip
    save_manifest(
        manifest_path,
        {"TheIsland.ark": load_manifest(manifest_path).get("TheIsland.ark", None)} if False else {},
    )

    # Build a correct manifest using the public format (avoid relying on internal types)
    payload = {
        "schema_version": 1,
        "files": {
            "TheIsland.ark": {"size_bytes": int(st1.st_size), "mtime_ns": int(st1.st_mtime_ns)},
        },
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = load_manifest(manifest_path)
    delta = compute_delta(savedarks, manifest)

    rels = [str(p.relative_to(savedarks)).replace("\\", "/") for p in delta]
    assert "p1.arkprofile" in rels
    assert "TheIsland.ark" not in rels


def test_manifest_delta_logic_changed_included(tmp_path: Path):
    savedarks = tmp_path / "SavedArks"
    f1 = savedarks / "Tribe1.arktribe"
    _touch(f1, b"x" * 3)

    manifest_path = tmp_path / MANIFEST_NAME
    st1 = f1.stat()
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "files": {
                    "Tribe1.arktribe": {"size_bytes": int(st1.st_size), "mtime_ns": int(st1.st_mtime_ns)},
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    # Change size => must be included
    _touch(f1, b"y" * 4)

    manifest = load_manifest(manifest_path)
    delta = compute_delta(savedarks, manifest)
    rels = [str(p.relative_to(savedarks)).replace("\\", "/") for p in delta]
    assert rels == ["Tribe1.arktribe"]


def test_backup_creates_zip_and_updates_manifest(tmp_path: Path):
    savedarks = tmp_path / "SavedArks"
    _touch(savedarks / "TheIsland.ark", b"a" * 10)
    _touch(savedarks / "p1.arkprofile", b"b" * 5)

    dest = tmp_path / "dest"
    manifest_path = dest / MANIFEST_NAME

    snap1 = create_backup_zip(
        savedarks_dir=savedarks,
        backup_dest_dir=dest,
        instance_id_fallback="1",
        manifest_path=manifest_path,
    )

    z1 = Path(snap1["backup_path"])
    assert z1.exists()

    with zipfile.ZipFile(z1, "r") as zf:
        names = sorted(zf.namelist())
    assert names == ["TheIsland.ark", "p1.arkprofile"]

    m1 = load_manifest(manifest_path)
    assert "TheIsland.ark" in m1
    assert "p1.arkprofile" in m1

    # Second backup with no changes => 0 files included
    snap2 = create_backup_zip(
        savedarks_dir=savedarks,
        backup_dest_dir=dest,
        instance_id_fallback="1",
        manifest_path=manifest_path,
    )
    z2 = Path(snap2["backup_path"])
    assert z2.exists()
    with zipfile.ZipFile(z2, "r") as zf:
        assert zf.namelist() == []
    assert snap2["files_included_count"] == 0


def test_derive_map_name_from_ark_filename_pattern(tmp_path: Path):
    savedarks = tmp_path / "SavedArks"
    _touch(savedarks / "TheIsland_01.02.2026_03.04.05.ark", b"x")
    assert derive_map_name_from_savedarks(savedarks, "1") == "TheIsland"


def test_admin_backup_refuses_when_not_stopped(tmp_path: Path):
    # Minimal fake orchestrator/AdminAPI wiring to validate STOPPED gate.
    from core.admin_api import AdminAPI

    class FakeState:
        STOPPED = "STOPPED"
        RUNNING = "RUNNING"

        def ensure_instance_exists(self, *_args, **_kwargs):
            return None

        def get_state(self, *_args, **_kwargs):
            return self.RUNNING

    class FakeOrch:
        def __init__(self):
            self._state_manager = FakeState()
            self._cluster_root = str(tmp_path)

        def get_instance_state(self, plugin_name, instance_id):
            self._state_manager.ensure_instance_exists(plugin_name, instance_id)
            return self._state_manager.get_state(plugin_name, instance_id)

        def _emit_event(self, *args, **kwargs):
            return None

    api = AdminAPI(FakeOrch())
    r = api.backup_instance("ark", "1", str(tmp_path / "backup_root"))
    assert r["status"] == "error"
    assert "STOPPED" in r["message"]