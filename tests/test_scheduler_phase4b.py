import json
import os
from datetime import datetime, timezone

import pytest

from core.orchestrator import Orchestrator
from core.plugin_registry import PluginRegistry
from core.state_manager import StateManager

pytest.skip("Phase 4B tests are out of scope; system frozen at Phase 4A.", allow_module_level=True)

# ############################################################
# SECTION: Scheduled Restart Architecture - Phase 4B Tests
# Purpose:
# Deterministic validation of time trigger layer and persistence.
# Lifecycle Ownership:
# Test Layer
# Phase:
# Scheduled Restart Architecture - Phase 4B (Time Trigger)
# Constraints:
# - No real clock usage
# - No background threads
# - Orchestrator.tick() only
# ############################################################

def dt(year, month, day, hour, minute):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def clean_state_file():
    path = os.path.join("data", "maintenance_state.json")
    if os.path.exists(path):
        os.remove(path)


def build_orchestrator():
    registry = PluginRegistry()
    state_manager = StateManager(state_file=None)
    orchestrator = Orchestrator(registry, state_manager)
    orchestrator.load_plugins()
    orchestrator.configure_scheduling(True, "04:00")
    return orchestrator


# ------------------------------------------------------------
# JSON file creation
# ------------------------------------------------------------

def test_json_created_if_missing():
    clean_state_file()
    build_orchestrator()

    path = os.path.join("data", "maintenance_state.json")
    assert os.path.exists(path)


# ------------------------------------------------------------
# ISO timestamp with offset
# ------------------------------------------------------------

def test_iso_timestamp_with_offset():
    clean_state_file()
    orchestrator = build_orchestrator()

    start_time = dt(2026, 2, 28, 4, 0)

    orchestrator.begin_maintenance_cycle(["ark"], start_time)
    orchestrator.tick(start_time)

    path = os.path.join("data", "maintenance_state.json")

    with open(path, "r") as f:
        data = json.load(f)

    value = data["last_cycle_start_time"]

    assert "T" in value
    assert "+" in value or "-" in value


# ------------------------------------------------------------
# Missed schedule detection
# ------------------------------------------------------------

def test_missed_schedule_detected():
    clean_state_file()
    orchestrator = build_orchestrator()

    # Before scheduled time
    orchestrator.tick(dt(2026, 2, 28, 3, 0))

    # After scheduled time without run
    orchestrator.tick(dt(2026, 2, 28, 5, 0))

    assert orchestrator.is_maintenance_missed() is True


# ------------------------------------------------------------
# Acknowledge clears missed
# ------------------------------------------------------------

def test_acknowledge_clears_missed():
    clean_state_file()
    orchestrator = build_orchestrator()

    orchestrator.tick(dt(2026, 2, 28, 5, 0))
    assert orchestrator.is_maintenance_missed() is True

    orchestrator.acknowledge_missed_schedule(
        dt(2026, 2, 28, 5, 5)
    )

    assert orchestrator.is_maintenance_missed() is False


# ------------------------------------------------------------
# Run missed schedule now
# ------------------------------------------------------------

def test_run_missed_schedule_now():
    clean_state_file()
    orchestrator = build_orchestrator()

    orchestrator.tick(dt(2026, 2, 28, 5, 0))
    assert orchestrator.is_maintenance_missed() is True

    orchestrator.run_missed_schedule_now(
        dt(2026, 2, 28, 5, 1)
    )

    assert orchestrator.is_maintenance_active() is True
    assert orchestrator.is_maintenance_missed() is False


# ------------------------------------------------------------
# Daily trigger fires once
# ------------------------------------------------------------

def test_daily_trigger_fires_once():
    clean_state_file()
    orchestrator = build_orchestrator()

    # Before scheduled time
    orchestrator.tick(dt(2026, 2, 28, 3, 59))
    assert not orchestrator.is_maintenance_active()

    # At scheduled time
    orchestrator.tick(dt(2026, 2, 28, 4, 0))
    assert orchestrator.is_maintenance_active()

    # Same day again should not start new cycle
    orchestrator.tick(dt(2026, 2, 28, 6, 0))
    assert orchestrator.is_maintenance_active()


# ------------------------------------------------------------
# Trigger blocked when paused
# ------------------------------------------------------------

def test_trigger_blocked_when_paused():
    clean_state_file()
    orchestrator = build_orchestrator()

    # Force scheduler paused
    orchestrator._scheduler._scheduling_paused = True

    orchestrator.tick(dt(2026, 2, 28, 4, 0))

    assert not orchestrator.is_maintenance_active()
