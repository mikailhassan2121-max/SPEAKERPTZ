import json

import pytest

from speakerptz.field.models import CheckResult, StepStatus
from speakerptz.field.record import FieldRecord


def test_record_step_persists_and_is_atomic(tmp_path):
    path = tmp_path / "field-setup.json"
    record = FieldRecord(str(path))
    record.record_step("mic_mapping", StepStatus.PASS, "4 seats mapped.")
    assert record.step_status("mic_mapping") is StepStatus.PASS
    assert record.step_detail("mic_mapping") == "4 seats mapped."
    assert not path.with_suffix(".json.tmp").exists()

    reloaded = FieldRecord(str(path))
    assert reloaded.step_status("mic_mapping") is StepStatus.PASS


def test_record_result_stores_check_result(tmp_path):
    record = FieldRecord(str(tmp_path / "field.json"))
    record.record_result(CheckResult("wide_shot", "Wide shot", StepStatus.PASS, "Camera 1 preset 20."))
    assert record.step_status("wide_shot") is StepStatus.PASS


def test_confirmation_requires_operator(tmp_path):
    record = FieldRecord(str(tmp_path / "field.json"))
    with pytest.raises(ValueError):
        record.confirm("joystick", operator="")


def test_confirmation_round_trips(tmp_path):
    path = tmp_path / "field.json"
    record = FieldRecord(str(path))
    record.confirm("joystick", operator="Jamie Lee", note="Verified with real hardware")
    assert record.is_confirmed("joystick")
    confirmation = record.confirmation("joystick")
    assert confirmation["operator"] == "Jamie Lee"
    assert confirmation["note"] == "Verified with real hardware"

    reloaded = FieldRecord(str(path))
    assert reloaded.is_confirmed("joystick")

    reloaded.revoke_confirmation("joystick")
    assert not reloaded.is_confirmed("joystick")


def test_confirm_uses_session_operator_when_not_passed(tmp_path):
    record = FieldRecord(str(tmp_path / "field.json"))
    record.set_session(operator="Session Operator")
    record.confirm("real_ptz_rehearsal")
    assert record.confirmation("real_ptz_rehearsal")["operator"] == "Session Operator"


def test_calibration_and_plan_payloads_round_trip(tmp_path):
    path = tmp_path / "field.json"
    record = FieldRecord(str(path))
    record.record_calibration({"channels": [], "room_noise_floor_db": -62.0})
    record.record_plan({"seats": [], "wide_shot": None})
    reloaded = FieldRecord(str(path))
    assert reloaded.calibration == {"channels": [], "room_noise_floor_db": -62.0}
    assert reloaded.plan == {"seats": [], "wide_shot": None}


def test_corrupt_or_wrong_schema_file_is_treated_as_empty(tmp_path):
    path = tmp_path / "field.json"
    path.write_text("not json", encoding="utf-8")
    record = FieldRecord(str(path))
    assert record.data["steps"] == {}

    path.write_text(json.dumps({"schema": 99, "steps": {"x": 1}}), encoding="utf-8")
    record2 = FieldRecord(str(path))
    assert record2.data["steps"] == {}


def test_clear_step_removes_recorded_status(tmp_path):
    record = FieldRecord(str(tmp_path / "field.json"))
    record.record_step("dry_run_rehearsal", StepStatus.PASS)
    record.clear_step("dry_run_rehearsal")
    assert record.step_status("dry_run_rehearsal") is None
