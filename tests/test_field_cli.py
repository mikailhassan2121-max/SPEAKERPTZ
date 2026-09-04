import io
import sys

import pytest
import yaml

import speakerptz.main as main_module


def _isolated_config(tmp_path):
    cfg = yaml.safe_load(open("config/room.yaml", encoding="utf-8"))
    cfg["runtime"]["log_dir"] = str(tmp_path / "logs")
    cfg["runtime"]["instance_lock_file"] = str(tmp_path / "speakerptz.lock")
    cfg["runtime"]["state_file"] = str(tmp_path / "runtime-state.json")
    path = tmp_path / "local.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def _run_main(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["speakerptz"] + argv)
    with pytest.raises(SystemExit) as excinfo:
        main_module.main()
    return excinfo.value


def test_field_readiness_cli_flag_exits_nonzero_when_not_ready(tmp_path, monkeypatch, capsys):
    cfg_path = _isolated_config(tmp_path)
    exc = _run_main(
        monkeypatch,
        [
            "--config", str(cfg_path),
            "--field-readiness",
            "--field-record", str(tmp_path / "field.json"),
        ],
    )
    out = capsys.readouterr().out
    assert "SPEAKERPTZ FIELD READINESS" in out
    assert exc.code == 1  # config/room.yaml alone is never ready for hardware rehearsal


def test_rehearsal_check_cli_flag_passes_and_records(tmp_path, monkeypatch, capsys):
    cfg_path = _isolated_config(tmp_path)
    record_path = tmp_path / "field.json"
    exc = _run_main(
        monkeypatch,
        [
            "--config", str(cfg_path),
            "--rehearsal-check",
            "--field-record", str(record_path),
            "--operator", "Jamie Lee",
        ],
    )
    out = capsys.readouterr().out
    assert "SPEAKERPTZ REHEARSAL CHECKLIST" in out
    assert exc.code == 0
    assert record_path.exists()


def test_field_confirm_cli_requires_operator(tmp_path, monkeypatch):
    exc = _run_main(
        monkeypatch,
        ["--field-confirm", "physical_joystick", "--field-record", str(tmp_path / "field.json")],
    )
    assert "operator" in str(exc.code).lower()


def test_field_confirm_cli_rejects_unknown_key(tmp_path, monkeypatch):
    exc = _run_main(
        monkeypatch,
        [
            "--field-confirm", "physical_jostick",  # typo: missing 'y'
            "--operator", "Jamie Lee",
            "--field-record", str(tmp_path / "field.json"),
        ],
    )
    assert "unknown key" in str(exc.code).lower()
    assert "physical_joystick" in str(exc.code)  # accepted values are listed

    from speakerptz.field.record import FieldRecord

    record = FieldRecord(str(tmp_path / "field.json"))
    assert not record.is_confirmed("physical_jostick")
    assert not record.is_confirmed("physical_joystick")


def test_field_confirm_cli_records_confirmation(tmp_path, monkeypatch, capsys):
    record_path = tmp_path / "field.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "speakerptz",
            "--field-confirm", "physical_joystick",
            "--operator", "Jamie Lee",
            "--field-note", "Verified at the console",
            "--field-record", str(record_path),
        ],
    )
    main_module.main()  # returns normally (no SystemExit) on success
    out = capsys.readouterr().out
    assert "Recorded human confirmation" in out

    from speakerptz.field.record import FieldRecord

    record = FieldRecord(str(record_path))
    assert record.is_confirmed("physical_joystick")
    assert record.confirmation("physical_joystick")["note"] == "Verified at the console"


def test_calibrate_cli_flag_requires_real_mode(tmp_path, monkeypatch):
    cfg_path = _isolated_config(tmp_path)  # room.yaml defaults to runtime.mode: simulate
    exc = _run_main(
        monkeypatch,
        ["--config", str(cfg_path), "--calibrate", "--field-record", str(tmp_path / "field.json")],
    )
    assert "real audio device" in str(exc.code)


def test_calibrate_cli_flag_wires_a_real_source_factory_not_the_simulator(tmp_path, monkeypatch):
    """Regression guard: --calibrate must capture real DVS/Dante audio in real mode.

    guided_calibration silently defaults to SimulatedAudioSource whenever it
    receives source_factory=None, so the --calibrate CLI path must always
    pass a real_source_factory(...) result when runtime.mode is not simulate.
    """
    import speakerptz.field.wizard as wizard_module

    cfg = yaml.safe_load(open("config/room.yaml", encoding="utf-8"))
    cfg["runtime"]["mode"] = "real"
    cfg["runtime"]["log_dir"] = str(tmp_path / "logs")
    cfg["runtime"]["instance_lock_file"] = str(tmp_path / "speakerptz.lock")
    cfg["runtime"]["state_file"] = str(tmp_path / "runtime-state.json")
    cfg_path = tmp_path / "local.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    sentinel_factory = object()
    factory_calls = []

    def fake_real_source_factory(passed_cfg, channels):
        factory_calls.append((passed_cfg, channels))
        return sentinel_factory

    calibration_calls = []

    def fake_guided_calibration(passed_cfg, seats, io, *, source_factory=None, **kwargs):
        calibration_calls.append(source_factory)
        from speakerptz.field.calibration import RoomCalibration

        return RoomCalibration((), None, (), (), (), {}, ())

    monkeypatch.setattr(wizard_module, "real_source_factory", fake_real_source_factory)
    monkeypatch.setattr(wizard_module, "guided_calibration", fake_guided_calibration)
    monkeypatch.setattr(sys, "argv", ["speakerptz", "--config", str(cfg_path), "--calibrate"])

    with pytest.raises(SystemExit):
        main_module.main()

    assert len(factory_calls) == 1
    assert factory_calls[0][1] == 4  # 4 seats in config/room.yaml's people section
    assert calibration_calls == [sentinel_factory]  # not None -- the simulator was never opted into


def test_field_setup_cli_flag_runs_and_exits_cleanly(tmp_path, monkeypatch, capsys):
    cfg_path = _isolated_config(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "speakerptz",
            "--config", str(cfg_path),
            "--field-setup",
            "--operator", "Jamie Lee",
            "--field-record", str(tmp_path / "field.json"),
        ],
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO("X\n"))
    main_module.main()  # the wizard's own loop exits via 'X'; main() returns normally
    out = capsys.readouterr().out
    assert "SPEAKERPTZ SCHOOL FIELD SETUP" in out
