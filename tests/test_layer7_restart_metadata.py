import json
from core.plugin_registry import PluginRegistry
from core.state_manager import StateManager
from core.orchestrator import Orchestrator
from tests.helpers_install import ensure_ready


def build_orchestrator(persistence_path):
    registry = PluginRegistry(plugin_dir="plugins")
    state = StateManager(state_file=None)
    orch = Orchestrator(registry, state, persistence_path=persistence_path, cluster_root=".")
    registry.load_all()
    return registry, state, orch


def test_layer7_last_restart_metadata_roundtrip_and_refusal_does_not_overwrite(tmp_path):
    path = tmp_path / "core_state.json"
    plugin = "ark"
    instance = "TestMap"

    # ----------------------------
    # 1) Successful scheduled restart creates metadata
    # ----------------------------
    _, state1, orch1 = build_orchestrator(str(path))

    ensure_ready(orch1, plugin, instance)
    orch1.start_instance(plugin, instance)

    r = orch1.restart_instance(plugin, instance, restart_reason="scheduled")
    assert r.get("status") == "success"

    meta1 = orch1._last_restart_metadata[(plugin, instance)]
    assert meta1["last_restart_source"] == "scheduled"
    assert isinstance(meta1["last_restart_time"], int)

    orch1.persist_state()

    # Final file is valid JSON and includes restart_metadata key
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert "restart_metadata" in data

    # ----------------------------
    # 2) Restore into new orchestrator — metadata must match
    # ----------------------------
    _, state2, orch2 = build_orchestrator(str(path))
    meta2 = orch2._last_restart_metadata[(plugin, instance)]
    assert meta2 == meta1

    # ----------------------------
    # 3) Refused scheduled restart must NOT overwrite metadata
    # ----------------------------
    orch2.disable_instance(plugin, instance, reason="test")
    refused = orch2.restart_instance(plugin, instance, restart_reason="scheduled")
    assert refused.get("status") != "success"

    # Must remain unchanged
    meta3 = orch2._last_restart_metadata[(plugin, instance)]
    assert meta3 == meta1