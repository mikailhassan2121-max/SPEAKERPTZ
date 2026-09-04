import json

import pytest

from speakerptz.runtime.instance import InstanceLock, InstanceLockError
from speakerptz.runtime.soak import run_soak_test
from speakerptz.runtime.state import RuntimeState


def test_instance_lock_rejects_second_controller(tmp_path):
    first = InstanceLock(str(tmp_path / "speakerptz.lock"))
    second = InstanceLock(str(tmp_path / "speakerptz.lock"))
    first.acquire()
    try:
        with pytest.raises(InstanceLockError, match="Another SPEAKERPTZ instance"):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()


def test_runtime_state_detects_unclean_exit_and_never_restores_auto(tmp_path):
    monotonic = [10.0]
    wall = [1000.0]
    path = tmp_path / "state.json"
    state = RuntimeState(str(path), clock=lambda: monotonic[0], wall_clock=lambda: wall[0])
    assert not state.previous_unclean_shutdown
    state.mark_started("0.9", "SIMULATION / DRY RUN")
    raw = json.loads(path.read_text())
    assert raw["clean_shutdown"] is False
    assert raw["auto_enabled"] is False

    restarted = RuntimeState(str(path), clock=lambda: monotonic[0], wall_clock=lambda: wall[0])
    assert restarted.previous_unclean_shutdown
    restarted.mark_clean_shutdown()
    clean = RuntimeState(str(path))
    assert not clean.previous_unclean_shutdown
    assert clean.read()["auto_enabled"] is False


def test_runtime_heartbeat_is_atomic_and_bounded_state(tmp_path):
    monotonic = [0.0]
    wall = [2000.0]
    path = tmp_path / "state.json"
    state = RuntimeState(str(path), clock=lambda: monotonic[0], wall_clock=lambda: wall[0])
    state.mark_started("0.9", "SIMULATION")
    monotonic[0] = 5.5
    wall[0] = 2005.5
    state.heartbeat(auto_enabled=True, audio_ok=True, camera_states={1: "ready"})
    payload = json.loads(path.read_text())
    assert payload["uptime_seconds"] == 5.5
    assert payload["camera_states"] == {"1": "ready"}
    assert not path.with_suffix(".json.tmp").exists()


def test_high_volume_soak_exercises_failures_without_invariant_breaks():
    summary = run_soak_test(iterations=3000, seed=23)
    assert summary["passed"]
    assert summary["invariant_failures"] == 0
    assert summary["speaker_events"] > 100
    assert summary["silence_events"] > 50
    assert summary["overlap_frames"] > 100
    assert summary["audio_dropouts"] > 50
    assert summary["camera_failures"] > 50
    assert summary["safely_blocked_moves"] > 50

