import yaml

from speakerptz.field.models import CheckResult, StepStatus
from speakerptz.field.readiness import REPORT_ROWS, ReadinessReport, build_readiness_report, render_readiness
from speakerptz.field.record import FieldRecord


def test_build_readiness_report_against_simulation_config():
    report = build_readiness_report("config/room.yaml", include_camera_connectivity=False)
    keys = {row.key for row in report.rows}
    assert keys == {key for key, _label in REPORT_ROWS}
    python_row = next(row for row in report.rows if row.key == "python")
    assert python_row.status is StepStatus.PASS


def test_build_readiness_report_fails_fast_on_missing_sections(tmp_path):
    bad_path = tmp_path / "broken.yaml"
    bad_path.write_text("just_a_key: true\n", encoding="utf-8")
    report = build_readiness_report(str(bad_path), include_camera_connectivity=False)
    config_row = next(row for row in report.rows if row.key == "configuration")
    assert config_row.status is StepStatus.FAIL
    # Every other row is skipped rather than silently omitted or fabricated as PASS.
    other_rows = [row for row in report.rows if row.key not in {"python", "configuration"}]
    assert other_rows
    assert all(row.status is StepStatus.SKIPPED for row in other_rows)


def test_build_readiness_report_fails_fast_on_syntactically_invalid_yaml(tmp_path):
    bad_path = tmp_path / "broken.yaml"
    bad_path.write_text("not: [valid, config\n", encoding="utf-8")
    report = build_readiness_report(str(bad_path), include_camera_connectivity=False)
    config_row = next(row for row in report.rows if row.key == "configuration")
    assert config_row.status is StepStatus.FAIL


def test_readiness_never_reports_human_only_rows_as_automated_pass():
    report = build_readiness_report("config/room.yaml", include_camera_connectivity=False)
    for key in ("manual_override", "physical_joystick"):
        row = next(r for r in report.rows if r.key == key)
        assert row.status in {StepStatus.HUMAN_REQUIRED, StepStatus.HUMAN_CONFIRMED}
        assert row.status is not StepStatus.PASS


def test_readiness_reflects_human_confirmations_recorded_in_field_record(tmp_path):
    record = FieldRecord(str(tmp_path / "field.json"))
    record.confirm("manual_override", operator="Jamie Lee")
    record.confirm("physical_joystick", operator="Jamie Lee")
    report = build_readiness_report("config/room.yaml", field_record=record, include_camera_connectivity=False)
    for key in ("manual_override", "physical_joystick"):
        row = next(r for r in report.rows if r.key == key)
        assert row.status is StepStatus.HUMAN_CONFIRMED


def _all_satisfied_rows(real_ptz_status=StepStatus.NOT_COMPLETED):
    return tuple(
        CheckResult(key, label, StepStatus.PASS, "ok")
        for key, label in REPORT_ROWS
        if key != "real_ptz_rehearsal"
    ) + (CheckResult("real_ptz_rehearsal", "Real PTZ rehearsal", real_ptz_status, "n/a"),)


def test_ready_for_hardware_rehearsal_requires_every_gating_row_satisfied():
    report = ReadinessReport(_all_satisfied_rows())
    assert report.ready_for_hardware_rehearsal
    assert not report.field_validated  # real_ptz_rehearsal itself is still outstanding


def test_ready_for_hardware_rehearsal_is_false_if_any_gating_row_unsatisfied():
    rows = list(_all_satisfied_rows())
    rows[0] = CheckResult(rows[0].key, rows[0].label, StepStatus.WARN, "needs attention")
    report = ReadinessReport(tuple(rows))
    assert not report.ready_for_hardware_rehearsal


def test_field_validated_requires_real_ptz_rehearsal_confirmation():
    report = ReadinessReport(_all_satisfied_rows(real_ptz_status=StepStatus.HUMAN_CONFIRMED))
    assert report.field_validated

    not_yet = ReadinessReport(_all_satisfied_rows(real_ptz_status=StepStatus.NOT_COMPLETED))
    assert not not_yet.field_validated


def test_readiness_report_against_live_room_config_is_not_yet_ready():
    # config/room.yaml is a development/simulation config; it must never claim
    # to be ready for a controlled hardware rehearsal on its own.
    report = build_readiness_report("config/room.yaml", include_camera_connectivity=False)
    assert not report.ready_for_hardware_rehearsal
    assert not report.field_validated


def test_render_readiness_shows_blocking_failures():
    report = build_readiness_report("config/room.yaml", include_camera_connectivity=False)
    text = render_readiness(report)
    assert "SPEAKERPTZ FIELD READINESS" in text
    assert "NOT YET READY" in text or "READY FOR CONTROLLED" in text
