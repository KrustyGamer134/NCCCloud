import os
import json

from core.plugin_registry import PluginRegistry
from core.state_manager import StateManager
from core.orchestrator import Orchestrator


def build_orchestrator(persistence_path):
    registry = PluginRegistry(plugin_dir="plugins")
    state = StateManager(state_file=None)
    orchestrator = Orchestrator(registry, state, persistence_path=persistence_path, cluster_root=".")
    registry.load_all()
    return registry, state, orchestrator


def test_layer6_roundtrip_persists_state_and_crash_metadata(tmp_path):
    path = tmp_path / "core_state.json"

    plugin = "ark"
    instance = "TestMap"

    # Create and mutate state
    _, state1, orch1 = build_orchestrator(str(path))

    orch1.disable_instance(plugin, instance, reason="test")
    assert state1.get_state(plugin, instance) == "DISABLED"

    # Create crash counters without triggering runtime behavior
    key = orch1._ensure_counter_entry(plugin, instance)
    orch1._crash_counters[key]["crash_total_count"] = 2
    orch1._crash_counters[key]["crash_stability_count"] = 1

    # Threshold overrides
    orch1.set_global_threshold(3)
    orch1.set_plugin_threshold(plugin, 5)
    orch1.set_instance_threshold(plugin, instance, 7)

    # Persist
    orch1.persist_state()
    assert os.path.exists(str(path))

    # New orchestrator should restore identical values (passive restore)
    _, state2, orch2 = build_orchestrator(str(path))

    assert state2.get_state(plugin, instance) == "DISABLED"
    assert orch2.get_crash_total_count(plugin, instance) == 2
    assert orch2.get_crash_stability_count(plugin, instance) == 1

    # Thresholds restored and precedence preserved
    assert orch2.get_effective_threshold(plugin, instance) == 7


def test_layer6_restore_is_passive_no_restart_called(tmp_path, capsys):
    path = tmp_path / "core_state.json"

    plugin = "ark"
    instance = "TestMap"

    # Write a state that would be tempting to "do something" with (but restore must be passive)
    _, state1, orch1 = build_orchestrator(str(path))
    state1.set_state(plugin, instance, "RUNNING")
    key = orch1._ensure_counter_entry(plugin, instance)
    orch1._crash_counters[key]["crash_total_count"] = 1
    orch1.persist_state()

    # Construct new orchestrator and ensure restart_instance() was NOT invoked during init
    capsys.readouterr()  # clear
    build_orchestrator(str(path))
    out = capsys.readouterr().out

    assert "RESTART FUNCTION LOADED FROM" not in out


def test_layer6_derive_crash_pause_on_load_no_pause_persisted(tmp_path):
    path = tmp_path / "core_state.json"

    plugin = "ark"
    instance = "TestMap"

    # Build first orchestrator and configure threshold
    _, state1, orch1 = build_orchestrator(str(path))

    # Ensure instance exists and is not DISABLED
    state1.set_state(plugin, instance, "STOPPED")

    # Threshold = 1 means crash_total_count >= 1 should derive pause
    orch1.set_global_threshold(1)

    key = orch1._ensure_counter_entry(plugin, instance)
    orch1._crash_counters[key]["crash_total_count"] = 1
    orch1._crash_counters[key]["crash_stability_count"] = 0

    orch1.persist_state()

    # Construct new orchestrator — pause must be derived, not persisted
    _, state2, orch2 = build_orchestrator(str(path))

    assert orch2.is_crash_restart_paused(plugin, instance) is True


def test_layer6_atomic_save_failure_does_not_corrupt_final_file(tmp_path, monkeypatch):
    """
    Proves atomic save cannot corrupt the final state file if a save fails mid-write
    (specifically: failure at the os.replace step after temp file is written).
    """
    path = tmp_path / "core_state.json"

    plugin = "ark"
    instance = "TestMap"

    # ----------------------------
    # 1) Create known-good final file (Snapshot A)
    # ----------------------------
    _, state1, orch1 = build_orchestrator(str(path))

    orch1.disable_instance(plugin, instance, reason="A")
    key = orch1._ensure_counter_entry(plugin, instance)
    orch1._crash_counters[key]["crash_total_count"] = 2
    orch1._crash_counters[key]["crash_stability_count"] = 1
    orch1.set_global_threshold(3)
    orch1.set_plugin_threshold(plugin, 5)
    orch1.set_instance_threshold(plugin, instance, 7)

    orch1.persist_state()

    final_before = path.read_text(encoding="utf-8")

    # Prove it's valid JSON
    json.loads(final_before)

    # ----------------------------
    # 2) Mutate to Snapshot B (would be persisted if replace succeeded)
    # ----------------------------
    orch1.reenable_instance(plugin, instance, reason="B")  # sets STOPPED + resets crash_total_count in your code
    # Make B clearly different
    key = orch1._ensure_counter_entry(plugin, instance)
    orch1._crash_counters[key]["crash_total_count"] = 99
    orch1._crash_counters[key]["crash_stability_count"] = 88
    orch1.set_global_threshold(1)
    orch1.set_plugin_threshold(plugin, 2)
    orch1.set_instance_threshold(plugin, instance, 4)

    # ----------------------------
    # 3) Inject failure at atomic replace (after temp is written)
    # ----------------------------
    # CorePersistence imports os and calls os.replace(...) for atomic rename.
    import core.persistence as persistence_module

    def fail_replace(src, dst):
        raise RuntimeError("Injected failure at os.replace")

    monkeypatch.setattr(persistence_module.os, "replace", fail_replace)

    try:
        orch1.persist_state()
        assert False, "Expected persist_state() to raise due to injected os.replace failure"
    except RuntimeError:
        pass

    # ----------------------------
    # 4) Final file must be unchanged and still valid JSON
    # ----------------------------
    final_after = path.read_text(encoding="utf-8")
    assert final_after == final_before
    json.loads(final_after)

    # ----------------------------
    # 5) Fresh orchestrator restore must match Snapshot A (last successful save)
    # ----------------------------
    _, state2, orch2 = build_orchestrator(str(path))

    assert state2.get_state(plugin, instance) == "DISABLED"
    assert orch2.get_crash_total_count(plugin, instance) == 2
    assert orch2.get_crash_stability_count(plugin, instance) == 1
    assert orch2.get_effective_threshold(plugin, instance) == 7

    # Temp file may exist; it must NOT have replaced/corrupted the final.
    # (We intentionally do not assert on tmp existence.)