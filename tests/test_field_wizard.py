import shutil

import pytest
import yaml

from speakerptz.core.config import load_config
from speakerptz.field.models import StepStatus
from speakerptz.field.record import FieldRecord
from speakerptz.field.wizard import WizardIO, guided_calibration, guided_seat_mapping, parse_seat_line, run_field_setup


def _scripted_io(lines):
    remaining = list(lines)
    log = []

    def fake_input(prompt=""):
        value = remaining.pop(0) if remaining else ""
        log.append((prompt, value))
        return value

    def fake_print(message=""):
        log.append(("<print>", str(message)))

    return WizardIO(input_fn=fake_input, print_fn=fake_print), log


# ---- parse_seat_line ----------------------------------------------------


def test_parse_seat_line_basic():
    seat = parse_seat_line("5 Board Chair", default_channel=1)
    assert seat.physical_input == 5
    assert seat.name == "Board Chair"
    assert seat.camera == 1
    assert seat.preset == 1  # defaults to the logical channel


def test_parse_seat_line_with_explicit_camera_and_preset():
    seat = parse_seat_line("9 Member A 2 3", default_channel=3)
    assert seat.physical_input == 9
    assert seat.name == "Member A"
    assert seat.camera == 2
    assert seat.preset == 3


def test_parse_seat_line_blank_returns_none():
    assert parse_seat_line("   ", default_channel=1) is None


def test_parse_seat_line_rejects_missing_name():
    with pytest.raises(ValueError):
        parse_seat_line("5", default_channel=1)


def test_parse_seat_line_rejects_non_numeric_input():
    with pytest.raises(ValueError):
        parse_seat_line("five Board Chair", default_channel=1)


def test_parse_seat_line_rejects_zero_input():
    with pytest.raises(ValueError):
        parse_seat_line("0 Board Chair", default_channel=1)


# ---- guided_seat_mapping -------------------------------------------------


def test_guided_seat_mapping_collects_seats_until_blank_line():
    io, _log = _scripted_io(["5 Board Chair", "6 Vice Chair", "", "1 20"])
    plan = guided_seat_mapping(io)
    assert [s.name for s in plan.seats] == ["Board Chair", "Vice Chair"]
    assert plan.seats[0].logical_channel == 1
    assert plan.seats[1].logical_channel == 2
    assert plan.wide_shot.camera == 1
    assert plan.wide_shot.preset == 20


def test_guided_seat_mapping_recovers_from_bad_line():
    io, log = _scripted_io(["notanumber Oops", "5 Board Chair", "", ""])
    plan = guided_seat_mapping(io)
    assert len(plan.seats) == 1
    assert any("ERROR" in entry[1] for entry in log if entry[0] == "<print>")


def test_guided_seat_mapping_extends_existing_plan():
    io, _log = _scripted_io(["6 Vice Chair", "", ""])
    from speakerptz.field.models import FieldPlan, SeatAssignment

    existing = FieldPlan(seats=[SeatAssignment(1, 5, "Board Chair", 1, 1)])
    plan = guided_seat_mapping(io, existing)
    assert [s.name for s in plan.seats] == ["Board Chair", "Vice Chair"]
    assert plan.seats[1].logical_channel == 2


# ---- guided_calibration ---------------------------------------------------


def test_guided_calibration_runs_against_simulated_source_with_injected_clock():
    from speakerptz.field.models import SeatAssignment

    seats = [SeatAssignment(1, 5, "Board Chair", 1, 1), SeatAssignment(2, 6, "Vice Chair", 1, 2)]
    io, _log = _scripted_io(["", ""])  # one Enter prompt per seat

    fake_time = [0.0]

    def clock():
        return fake_time[0]

    def source_factory():
        class _FakeSource:
            def read_observation(self):
                from speakerptz.audio.vad import AudioObservation

                fake_time[0] += 1.0  # advances the loop past its duration immediately
                return AudioObservation([-20.0, -60.0], [0.9, 0.02])

        return _FakeSource()

    result = guided_calibration(
        {},
        seats,
        io,
        source_factory=source_factory,
        quiet_seconds=0.5,
        speech_seconds=0.5,
        frame_delay=0.0,
        clock=clock,
    )
    assert result.channels  # produced a row per seat


def test_guided_calibration_stops_a_stoppable_source_even_on_error():
    from speakerptz.field.models import SeatAssignment

    seats = [SeatAssignment(1, 5, "Board Chair", 1, 1)]
    io, _log = _scripted_io([""])
    fake_time = [0.0]
    stopped = []

    def clock():
        fake_time[0] += 1.0
        return fake_time[0]

    class _StoppableSource:
        def read_observation(self):
            from speakerptz.audio.vad import AudioObservation

            return AudioObservation([-20.0], [0.9])

        def stop(self):
            stopped.append(True)

    result = guided_calibration(
        {},
        seats,
        io,
        source_factory=lambda: _StoppableSource(),
        quiet_seconds=0.5,
        speech_seconds=0.5,
        frame_delay=0.0,
        clock=clock,
    )
    assert result.channels
    assert stopped == [True]


def test_guided_calibration_stops_source_even_when_session_raises():
    from speakerptz.field.models import SeatAssignment

    stopped = []

    class _StoppableSource:
        def read_observation(self):
            raise RuntimeError("simulated audio failure")

        def stop(self):
            stopped.append(True)

    io, _log = _scripted_io([])
    with pytest.raises(RuntimeError):
        guided_calibration(
            {},
            [SeatAssignment(1, 5, "Board Chair", 1, 1)],
            io,
            source_factory=lambda: _StoppableSource(),
            quiet_seconds=0.5,
            speech_seconds=0.5,
            frame_delay=0.0,
            clock=lambda: 0.0,
        )
    assert stopped == [True]


# ---- run_field_setup: end-to-end scripted session -------------------------


def test_run_field_setup_reentering_seat_mapping_preserves_wide_shot(tmp_path):
    cfg_path = tmp_path / "local.yaml"
    shutil.copy("config/room.yaml", cfg_path)
    record = FieldRecord(str(tmp_path / "field.json"))

    io, _log = _scripted_io(
        [
            "F",
            "5 Board Chair",
            "",
            "1 20",  # wide shot set on first pass
            "F",
            "6 Vice Chair",
            "",
            "",  # blank: keep the existing wide shot, don't clear it
            "X",
        ]
    )
    run_field_setup(str(cfg_path), operator="Jamie Lee", io=io, record=record)
    plan = record.plan
    assert plan is not None
    assert len(plan["seats"]) == 2
    assert plan["wide_shot"] == {"camera": 1, "preset": 20}


def test_run_field_setup_calibration_step_satisfies_readiness_mic_calibration_row(tmp_path, monkeypatch):
    from speakerptz.field import wizard as wizard_module
    from speakerptz.field.calibration import ChannelCalibration, RoomCalibration
    from speakerptz.field.readiness import build_readiness_report

    # guided_calibration's own real-time pacing is exercised by
    # test_guided_calibration_*; here only the dispatch logic in
    # run_field_setup's "calibration" branch is under test, so stub the
    # (slow, real-time) collection loop with a fast canned WARN result.
    warn_result = RoomCalibration(
        channels=(
            ChannelCalibration(1, 5, "Board Chair", -60.0, -20.0, 40.0, 10, 10, "ok"),
            ChannelCalibration(2, 6, "Vice Chair", -60.0, None, None, 10, 0, "no_speech"),
        ),
        room_noise_floor_db=-60.0,
        suspected_bleed_pairs=(),
        dead_channels=(),
        unverified_channels=(2,),
        recommended={},
        warnings=("Channels without a verified speech sample: 2",),
    )
    monkeypatch.setattr(wizard_module, "guided_calibration", lambda *a, **k: warn_result)

    cfg_path = tmp_path / "local.yaml"
    shutil.copy("config/room.yaml", cfg_path)
    record = FieldRecord(str(tmp_path / "field.json"))

    io, _log = _scripted_io(["F", "5 Board Chair", "6 Vice Chair", "", "1 20", "G", "X"])
    run_field_setup(str(cfg_path), operator="Jamie Lee", io=io, record=record)

    assert record.step_status("mic_calibration") is StepStatus.WARN

    report = build_readiness_report(str(cfg_path), field_record=record, include_camera_connectivity=False)
    mic_calibration_row = next(r for r in report.rows if r.key == "mic_calibration")
    # Regression guard for the wizard/readiness key mismatch: a WARN recorded
    # by the wizard must show up as WARN here, never silently promoted to PASS.
    assert mic_calibration_row.status is StepStatus.WARN
    assert mic_calibration_row.detail != "Calibration data recorded."


def test_run_field_setup_end_to_end(tmp_path):
    cfg_path = tmp_path / "local.yaml"
    shutil.copy("config/room.yaml", cfg_path)
    record_path = tmp_path / "field.json"

    io, log = _scripted_io(
        [
            "F",
            "5 Board Chair 1 1",
            "6 Vice Chair 1 2",
            "9 Member A 1 3",
            "10 Member B 1 4",
            "",
            "1 20",
            "H",
            "L",
            "y",
            "S",
            "X",
        ]
    )
    record = FieldRecord(str(record_path))
    result_record = run_field_setup(str(cfg_path), operator="Jamie Lee", io=io, record=record)

    assert result_record.step_status("seat_mapping") is StepStatus.PASS
    assert result_record.step_status("preset_mapping") is StepStatus.PASS
    assert result_record.plan is not None and len(result_record.plan["seats"]) == 4

    cfg, routes = load_config(str(cfg_path))
    assert routes[1].name == "Board Chair"
    assert cfg["audio"]["channel_map"] == [5, 6, 9, 10]

    # A timestamped backup of the original config was preserved.
    backups = list(tmp_path.glob("local.yaml.bak-*"))
    assert backups


def test_run_field_setup_camera_entry_writes_config(tmp_path):
    cfg_path = tmp_path / "local.yaml"
    shutil.copy("config/room.yaml", cfg_path)
    record_path = tmp_path / "field.json"

    io, _log = _scripted_io(
        [
            "I",
            "2",
            "Camera 2",
            "simulator",
            "X",
        ]
    )
    record = FieldRecord(str(record_path))
    run_field_setup(str(cfg_path), operator="Jamie Lee", io=io, record=record)

    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    ids = {c["id"] for c in cfg["cameras"]}
    assert 2 in ids


def test_run_field_setup_human_confirmation_flow(tmp_path):
    cfg_path = tmp_path / "local.yaml"
    shutil.copy("config/room.yaml", cfg_path)
    record = FieldRecord(str(tmp_path / "field.json"))

    io, _log = _scripted_io(["Q", "yes", "X"])
    run_field_setup(str(cfg_path), operator="Jamie Lee", io=io, record=record)
    assert record.is_confirmed("physical_joystick")
    assert record.confirmation("physical_joystick")["operator"] == "Jamie Lee"


def test_run_field_setup_rehearsal_step_records_result(tmp_path):
    cfg_path = tmp_path / "local.yaml"
    shutil.copy("config/room.yaml", cfg_path)
    record = FieldRecord(str(tmp_path / "field.json"))

    io, _log = _scripted_io(["O", "X"])
    run_field_setup(str(cfg_path), operator="Jamie Lee", io=io, record=record)
    assert record.step_status("rehearsal") is StepStatus.PASS
    assert record.step_status("dry_run_rehearsal") is StepStatus.PASS


def test_run_field_setup_edge_case_step_prompts_for_manual_override(tmp_path):
    cfg_path = tmp_path / "local.yaml"
    shutil.copy("config/room.yaml", cfg_path)
    record = FieldRecord(str(tmp_path / "field.json"))

    io, _log = _scripted_io(["P", "yes", "X"])
    run_field_setup(str(cfg_path), operator="Jamie Lee", io=io, record=record)
    assert record.step_status("rehearsal_edge_cases") is StepStatus.PASS
    assert record.is_confirmed("manual_override")
    assert record.confirmation("manual_override")["operator"] == "Jamie Lee"


def test_wizard_human_confirmation_keys_match_readiness_report_keys(tmp_path):
    """A confirmation recorded through the wizard must satisfy the readiness report.

    Regression guard: wizard.py and readiness.py must agree on confirmation
    keys ('physical_joystick', 'real_ptz_rehearsal'), or a confirmation made
    through field_setup.bat would silently never show up in
    field_readiness.bat's output.
    """
    from speakerptz.field.readiness import build_readiness_report

    cfg_path = tmp_path / "local.yaml"
    shutil.copy("config/room.yaml", cfg_path)
    record = FieldRecord(str(tmp_path / "field.json"))

    io, _log = _scripted_io(["Q", "yes", "R", "yes", "X"])
    run_field_setup(str(cfg_path), operator="Jamie Lee", io=io, record=record)

    report = build_readiness_report(str(cfg_path), field_record=record, include_camera_connectivity=False)
    joystick_row = next(r for r in report.rows if r.key == "physical_joystick")
    real_ptz_row = next(r for r in report.rows if r.key == "real_ptz_rehearsal")
    assert joystick_row.status is StepStatus.HUMAN_CONFIRMED
    assert real_ptz_row.status is StepStatus.HUMAN_CONFIRMED


def test_run_field_setup_quits_immediately_without_operator_prompts():
    io, log = _scripted_io(["X"])
    from speakerptz.field.record import FieldRecord as FR

    record = FR.__new__(FR)  # avoid touching disk; only used for set_session below
    record.data = {"schema": 1, "steps": {}, "confirmations": {}, "calibration": None, "plan": None, "operator": "", "site_label": ""}
    record.path = None
    record.save = lambda: None
    record._wall_clock = lambda: 0.0
    run_field_setup("config/room.yaml", operator="Jamie Lee", io=io, record=record)
    assert any("Exit the guided setup" in entry[1] for entry in log if entry[0] == "<print>")
