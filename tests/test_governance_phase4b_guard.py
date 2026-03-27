import pytest


def test_phase4b_like_config_is_rejected():
    # Minimal Phase 4B marker payload (time-of-day scheduling intent)
    cfg = {"daily": {"time_of_day": "04:00"}}

    from core.scheduler_engine import SchedulerEngine

    engine = SchedulerEngine(orchestrator=None)

    with pytest.raises(ValueError) as excinfo:
        engine.apply_schedule_config(cfg)

    assert "Phase 4B not authorized" in str(excinfo.value)


def test_phase4a_or_empty_config_is_noop():
    from core.scheduler_engine import SchedulerEngine

    engine = SchedulerEngine(orchestrator=None)

    # Empty config must not raise
    engine.apply_schedule_config({})

    # None must not raise
    engine.apply_schedule_config(None)