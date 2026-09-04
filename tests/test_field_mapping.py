import pytest
import yaml

from speakerptz.core.config import load_config, validate_config
from speakerptz.field.mapping import (
    apply_calibration,
    apply_plan,
    backup_config,
    peak_physical_input,
    plan_from_config,
    set_camera_entry,
    validate_plan,
    write_config,
)
from speakerptz.field.models import FieldPlan, SeatAssignment, StepStatus, WideShotAssignment


def _base_config():
    return yaml.safe_load(open("config/room.yaml", encoding="utf-8"))


# ---- peak_physical_input --------------------------------------------------


def test_peak_physical_input_picks_clear_winner():
    channel, reason = peak_physical_input([-70, -70, -20, -70])
    assert channel == 3
    assert "input 3" in reason


def test_peak_physical_input_rejects_ambiguous_levels():
    channel, reason = peak_physical_input([-70, -70, -20, -19])
    assert channel is None
    assert "within" in reason


def test_peak_physical_input_rejects_quiet_room():
    channel, reason = peak_physical_input([-70, -70, -70, -70])
    assert channel is None
    assert "below" in reason


def test_peak_physical_input_rejects_empty_levels():
    channel, reason = peak_physical_input([])
    assert channel is None


# ---- validate_plan ----------------------------------------------------


def _two_seat_plan(**overrides):
    seats = overrides.pop("seats", None) or [
        SeatAssignment(1, 5, "Board Chair", 1, 1),
        SeatAssignment(2, 6, "Vice Chair", 1, 2),
    ]
    wide = overrides.pop("wide_shot", WideShotAssignment(1, 20))
    return FieldPlan(seats=seats, wide_shot=wide, **overrides)


def test_validate_plan_passes_for_clean_plan():
    plan = _two_seat_plan()
    results = validate_plan(plan, {1: {"driver": "simulator", "enabled": True}})
    assert all(result.status is not StepStatus.FAIL for result in results)


def test_validate_plan_rejects_empty_plan():
    results = validate_plan(FieldPlan())
    assert any(result.status is StepStatus.FAIL for result in results)


def test_validate_plan_rejects_gaps_in_logical_channels():
    plan = _two_seat_plan(seats=[SeatAssignment(1, 5, "A", 1, 1), SeatAssignment(3, 6, "B", 1, 2)])
    results = validate_plan(plan)
    seat_result = next(r for r in results if r.key == "plan_seats")
    assert seat_result.status is StepStatus.FAIL


def test_validate_plan_rejects_duplicate_physical_inputs():
    plan = _two_seat_plan(seats=[SeatAssignment(1, 5, "A", 1, 1), SeatAssignment(2, 5, "B", 1, 2)])
    results = validate_plan(plan)
    result = next(r for r in results if r.key == "plan_physical_inputs")
    assert result.status is StepStatus.FAIL


def test_validate_plan_warns_on_generic_names():
    plan = _two_seat_plan(seats=[SeatAssignment(1, 5, "Seat 1", 1, 1), SeatAssignment(2, 6, "Mic 2", 1, 2)])
    results = validate_plan(plan)
    result = next(r for r in results if r.key == "plan_names")
    assert result.status is StepStatus.WARN


def test_validate_plan_rejects_unnamed_seat():
    plan = _two_seat_plan(seats=[SeatAssignment(1, 5, "", 1, 1), SeatAssignment(2, 6, "B", 1, 2)])
    results = validate_plan(plan)
    result = next(r for r in results if r.key == "plan_names")
    assert result.status is StepStatus.FAIL


def test_validate_plan_rejects_unknown_camera():
    plan = _two_seat_plan()
    results = validate_plan(plan, {2: {"driver": "simulator", "enabled": True}})
    result = next(r for r in results if r.key == "plan_cameras")
    assert result.status is StepStatus.FAIL


def test_validate_plan_rejects_disabled_camera_reference():
    plan = _two_seat_plan()
    results = validate_plan(plan, {1: {"driver": "simulator", "enabled": False}})
    result = next(r for r in results if r.key == "plan_cameras")
    assert result.status is StepStatus.FAIL


def test_validate_plan_enforces_visca_preset_range():
    plan = _two_seat_plan(seats=[SeatAssignment(1, 5, "A", 1, 99), SeatAssignment(2, 6, "B", 1, 1)])
    results = validate_plan(plan, {1: {"driver": "visca", "enabled": True}})
    result = next(r for r in results if r.key == "plan_cameras")
    assert result.status is StepStatus.FAIL


def test_validate_plan_requires_wide_shot():
    plan = _two_seat_plan(wide_shot=None)
    results = validate_plan(plan)
    result = next(r for r in results if r.key == "plan_wide_shot")
    assert result.status is StepStatus.FAIL


def test_validate_plan_warns_when_disabled_channel_not_mapped():
    plan = _two_seat_plan(disabled_channels=[9])
    results = validate_plan(plan)
    result = next(r for r in results if r.key == "plan_disabled_channels")
    assert result.status is StepStatus.FAIL


def test_validate_plan_warns_shared_preset():
    plan = _two_seat_plan(seats=[SeatAssignment(1, 5, "A", 1, 1), SeatAssignment(2, 6, "B", 1, 1)])
    results = validate_plan(plan)
    result = next(r for r in results if r.key == "plan_presets")
    assert result.status is StepStatus.WARN


# ---- plan_from_config / apply_plan round trip --------------------------


def test_plan_from_config_reads_existing_room_yaml():
    cfg = _base_config()
    plan = plan_from_config(cfg)
    assert len(plan.seats) == 4
    assert plan.seats[0].physical_input == 1
    assert plan.wide_shot == WideShotAssignment(1, 20)


def test_apply_plan_updates_channel_map_and_people_and_validates():
    cfg = _base_config()
    plan = FieldPlan(
        seats=[
            SeatAssignment(1, 5, "Board Chair", 1, 1),
            SeatAssignment(2, 6, "Vice Chair", 1, 2),
            SeatAssignment(3, 9, "Member A", 1, 3),
            SeatAssignment(4, 10, "Member B", 1, 4),
        ],
        wide_shot=WideShotAssignment(1, 20),
    )
    updated = apply_plan(cfg, plan)
    assert updated["audio"]["channel_map"] == [5, 6, 9, 10]
    assert updated["audio"]["channels"] == 4
    assert [p["name"] for p in updated["people"]] == ["Board Chair", "Vice Chair", "Member A", "Member B"]
    # apply_plan must not mutate the caller's dict.
    assert cfg["audio"]["channel_map"] == [1, 2, 3, 4]
    validate_config(updated)


def test_apply_plan_rejects_empty_plan():
    cfg = _base_config()
    with pytest.raises(ValueError):
        apply_plan(cfg, FieldPlan())


def test_apply_plan_marks_disabled_seats():
    cfg = _base_config()
    plan = FieldPlan(
        seats=[
            SeatAssignment(1, 5, "A", 1, 1, enabled=True),
            SeatAssignment(2, 6, "B", 1, 2, enabled=False),
        ],
        wide_shot=WideShotAssignment(1, 20),
    )
    updated = apply_plan(cfg, plan)
    assert updated["audio"]["disabled_channels"] == [2]


def test_apply_calibration_updates_thresholds_and_offsets():
    cfg = _base_config()

    class FakeCalibration:
        recommended = {
            "absolute_threshold_db": -55.0,
            "signal_margin_db": 10.0,
            "level_offsets_db": [1.0, -1.0, 0.0, 0.0],
            "disabled_channels": [3],
            "bleed_pairs": [[1, 2]],
        }

    updated = apply_calibration(cfg, FakeCalibration())
    assert updated["audio"]["absolute_threshold_db"] == -55.0
    assert updated["audio"]["signal_margin_db"] == 10.0
    assert updated["audio"]["level_offsets_db"] == [1.0, -1.0, 0.0, 0.0]
    assert updated["audio"]["disabled_channels"] == [3]
    # bleed_pairs is opt-in and defaults to being left alone.
    assert updated["audio"]["bleed_pairs"] == []
    assert cfg["audio"]["absolute_threshold_db"] != -55.0


def test_apply_calibration_can_opt_into_bleed_pairs():
    cfg = _base_config()

    class FakeCalibration:
        recommended = {"bleed_pairs": [[1, 2]]}

    updated = apply_calibration(cfg, FakeCalibration(), apply_bleed=True)
    assert updated["audio"]["bleed_pairs"] == [[1, 2]]


def test_apply_calibration_drops_stale_length_level_offsets(tmp_path):
    """Regression guard: a calibration frozen against an old seat count must
    never write a level_offsets_db whose length disagrees with the config it
    is being applied to -- validate_config rejects that and the resulting
    config/local.yaml becomes unloadable by every field tool.
    """
    cfg = _base_config()
    cfg["audio"]["channels"] = 5  # seat count changed after calibration ran
    cfg["audio"]["channel_map"] = [1, 2, 3, 4, 5]
    cfg["audio"]["level_offsets_db"] = [0.0] * 5  # apply_plan already resized this correctly

    class FakeCalibration:
        # Frozen from a 4-seat calibration session.
        recommended = {"level_offsets_db": [1.0, -1.0, 0.0, 0.0]}

    updated = apply_calibration(cfg, FakeCalibration())
    # The stale 4-length recommendation was not applied; the caller's
    # already-correct 5-length offsets are left untouched.
    assert updated["audio"]["level_offsets_db"] == [0.0] * 5
    validate_config(updated)


def test_apply_calibration_drops_stale_disabled_channels_and_bleed_pairs():
    cfg = _base_config()
    cfg["audio"]["channels"] = 2
    cfg["audio"]["channel_map"] = [1, 2]
    cfg["audio"]["level_offsets_db"] = [0.0, 0.0]
    cfg["people"] = [
        {"mic_channel": 1, "name": "Seat 1", "camera": 1, "preset": 1},
        {"mic_channel": 2, "name": "Seat 2", "camera": 1, "preset": 2},
    ]

    class FakeCalibration:
        # Frozen from a session where channels 3/4 still existed.
        recommended = {"disabled_channels": [3], "bleed_pairs": [[3, 4]]}

    updated = apply_calibration(cfg, FakeCalibration(), apply_bleed=True)
    assert updated["audio"]["disabled_channels"] == []
    assert updated["audio"]["bleed_pairs"] == []
    validate_config(updated)


def test_apply_calibration_still_applies_offsets_matching_current_channel_count():
    cfg = _base_config()  # 4 channels

    class FakeCalibration:
        recommended = {"level_offsets_db": [1.0, -1.0, 0.5, 0.0]}

    updated = apply_calibration(cfg, FakeCalibration())
    assert updated["audio"]["level_offsets_db"] == [1.0, -1.0, 0.5, 0.0]
    validate_config(updated)


def test_set_camera_entry_inserts_and_replaces():
    cfg = _base_config()
    updated = set_camera_entry(cfg, {"id": 2, "name": "Camera 2", "driver": "simulator", "enabled": True})
    assert len(updated["cameras"]) == 2
    updated2 = set_camera_entry(updated, {"id": 1, "name": "Camera 1 renamed", "driver": "simulator", "enabled": True})
    names = {c["id"]: c["name"] for c in updated2["cameras"]}
    assert names[1] == "Camera 1 renamed"
    assert len(updated2["cameras"]) == 2
    # Original untouched.
    assert len(cfg["cameras"]) == 1


def test_write_config_backs_up_and_reloads(tmp_path):
    cfg = _base_config()
    path = tmp_path / "local.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    updated = dict(cfg)
    updated["people"] = [{"mic_channel": 1, "name": "New Name", "camera": 1, "preset": 1}]
    updated["audio"] = dict(cfg["audio"])
    updated["audio"]["channels"] = 1
    updated["audio"]["channel_map"] = [1]
    updated["audio"]["level_offsets_db"] = []

    backup = write_config(str(path), updated)
    assert backup is not None and backup.exists()
    assert "Seat 1" in backup.read_text(encoding="utf-8")  # backup holds the prior content
    assert "New Name" not in backup.read_text(encoding="utf-8")
    reloaded_cfg, routes = load_config(str(path))
    assert routes[1].name == "New Name"


def test_write_config_without_backup_when_file_missing(tmp_path):
    cfg = _base_config()
    path = tmp_path / "local.yaml"
    backup = write_config(str(path), cfg, backup=True)
    assert backup is None
    assert path.exists()


def test_backup_config_returns_none_for_missing_file(tmp_path):
    assert backup_config(str(tmp_path / "missing.yaml")) is None
