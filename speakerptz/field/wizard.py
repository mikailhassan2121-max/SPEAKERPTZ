from __future__ import annotations

import time
from dataclasses import dataclass

from speakerptz.audio.channelmap import normalize_channel_map
from speakerptz.core.config import ConfigError, load_config

from .calibration import CalibrationSession, RoomCalibration, render_calibration
from .camera_check import check_camera_config, probe_camera
from .mapping import (
    apply_calibration,
    apply_plan,
    set_camera_entry,
    validate_plan,
    write_config,
)
from .models import FieldPlan, SeatAssignment, StepStatus, WideShotAssignment
from .readiness import build_readiness_report, render_readiness
from .record import FieldRecord
from .rehearsal import render_rehearsal, run_automated_scenarios


# The lettered flow from the project brief. Steps are shown to the operator in
# this order every time the menu is drawn; nothing here forces a strict linear
# path (an operator may re-run any step), but the checklist and readiness
# report make the *recommended* order visible at a glance.
FLOW_STEPS: tuple[tuple[str, str, str], ...] = (
    ("A", "no_live_meeting", "Confirm no live meeting is happening right now"),
    ("B", "real_control_off", "Confirm real PTZ control is OFF (real_control_enabled: false)"),
    ("C", "doctor", "Run the startup doctor"),
    ("D", "dante_dvs", "Verify Dante Virtual Soundcard is visible to Windows"),
    ("E", "identify_channels", "Identify each physical mic channel (identify_dante_channels.bat)"),
    ("F", "seat_mapping", "Map each mic to a seat/person"),
    ("G", "calibration", "Calibrate each mic / noise floor"),
    ("H", "verify_mics", "Verify all configured microphones"),
    ("I", "camera_entry", "Enter camera model/IP/protocol information"),
    ("J", "camera_connectivity", "Test camera connectivity"),
    ("K", "manual_preset_check", "Manually verify camera presets one at a time (camera_test.bat)"),
    ("L", "preset_mapping", "Map each seat to its camera/preset"),
    ("M", "wide_shot", "Configure and verify the wide shot"),
    ("N", "dry_run", "Run speaker-detection dry run with simulated camera requests"),
    ("O", "rehearsal", "Rehearse with multiple people speaking"),
    ("P", "rehearsal_edge_cases", "Test interjections, silence, overlap, manual override"),
    ("Q", "physical_joystick", "Verify the physical joystick / manual operation"),
    ("R", "real_ptz_rehearsal", "Controlled real-PTZ rehearsal (only after explicit approval)"),
    ("S", "readiness_report", "Generate the final setup/readiness report"),
)

HUMAN_ONLY_STEPS = {"no_live_meeting", "real_control_off", "physical_joystick", "real_ptz_rehearsal"}


@dataclass
class WizardIO:
    """Injectable input/output so the wizard can be driven by tests or a real console."""

    input_fn: callable = input
    print_fn: callable = print

    def prompt(self, message: str) -> str:
        return self.input_fn(message)

    def say(self, message: str = "") -> None:
        self.print_fn(message)


def parse_seat_line(line: str, default_channel: int) -> SeatAssignment | None:
    """Parse one guided-prompt line into a SeatAssignment.

    Expected shape: "<physical_input> <name> [camera] [preset]", e.g.
    "5 Board Chair 1 1". Camera/preset default to 1 and the seat's own logical
    channel number when omitted, so the operator can fill those in later
    during preset mapping. Returns None for a blank line (skip this seat).
    """
    text = line.strip()
    if not text:
        return None
    parts = text.split()
    if len(parts) < 2:
        raise ValueError(
            "Expected: <physical DVS input> <seat/person name> [camera id] [preset], e.g. '5 Board Chair 1 1'."
        )
    try:
        physical_input = int(parts[0])
    except ValueError as exc:
        raise ValueError(f"'{parts[0]}' is not a valid physical input number.") from exc
    if physical_input < 1:
        raise ValueError("Physical input numbers are 1-based.")

    camera = 1
    preset = default_channel
    name_tokens = parts[1:]
    if len(name_tokens) >= 2 and name_tokens[-2].isdigit() and name_tokens[-1].isdigit():
        preset = int(name_tokens[-1])
        camera = int(name_tokens[-2])
        name_tokens = name_tokens[:-2]
    name = " ".join(name_tokens).strip()
    if not name:
        raise ValueError("A seat/person name is required.")
    return SeatAssignment(
        logical_channel=default_channel,
        physical_input=physical_input,
        name=name,
        camera=camera,
        preset=preset,
        enabled=True,
    )


def guided_seat_mapping(io: WizardIO, existing: FieldPlan | None = None) -> FieldPlan:
    """Interactively build a FieldPlan; loops until the operator sends a blank line."""
    io.say("")
    io.say("SEAT MAPPING")
    io.say("Walk to one board microphone, speak into it, note the physical input that")
    io.say("peaked on identify_dante_channels.bat, then enter it here.")
    io.say("Format: <physical input> <seat/person name> [camera id] [preset]")
    io.say("Example: 5 Board Chair 1 1")
    io.say("Enter a blank line when every seat has been added.")
    seats: list[SeatAssignment] = list(existing.seats) if existing else []
    channel = len(seats) + 1
    while True:
        line = io.prompt(f"Seat {channel} (blank to finish)> ")
        if not line.strip():
            break
        try:
            seat = parse_seat_line(line, channel)
        except ValueError as exc:
            io.say(f"  ERROR: {exc}")
            continue
        if seat is None:
            break
        seats.append(seat)
        io.say(f"  Added: mic {seat.logical_channel} <- DVS input {seat.physical_input} -> {seat.name}")
        channel += 1
    wide = existing.wide_shot if existing else None
    if seats:
        wide_line = io.prompt("Wide shot: <camera id> <preset> (blank to keep unset)> ")
        if wide_line.strip():
            try:
                cam_text, preset_text = wide_line.split()
                wide = WideShotAssignment(int(cam_text), int(preset_text))
            except ValueError:
                io.say("  ERROR: expected two numbers, e.g. '1 20'. Wide shot left unset.")
    return FieldPlan(seats=seats, wide_shot=wide)


def guided_calibration(
    cfg: dict,
    seats: list[SeatAssignment],
    io: WizardIO,
    *,
    source_factory=None,
    quiet_seconds: float = 3.0,
    speech_seconds: float = 2.5,
    frame_delay: float = 0.05,
    clock=time.monotonic,
) -> RoomCalibration:
    """Drive one guided calibration session using a live or simulated audio source.

    `source_factory()` must return an object exposing `read_observation()` (both
    RealAudioSource and SimulatedAudioSource already do). Only per-channel dB
    levels ever leave the source; nothing here touches raw samples.
    """
    if not seats:
        raise ValueError("Map seats before calibrating.")
    channels = len(seats)
    channel_map = [seat.physical_input for seat in seats]
    names = [seat.name for seat in seats]
    session = CalibrationSession(channels, channel_map=channel_map, names=names)

    if source_factory is None:
        from speakerptz.audio.simulator import SimulatedAudioSource

        source_factory = lambda: SimulatedAudioSource(channels)

    io.say("")
    io.say("ROOM CALIBRATION")
    io.say(f"Stay quiet for {quiet_seconds:.0f} seconds to sample the room noise floor...")
    source = source_factory()
    started = clock()
    while clock() - started < quiet_seconds:
        session.add_noise_frame(source.read_observation().levels_db)
        time.sleep(frame_delay)
    io.say(f"Captured {session.noise_frame_count} quiet-room frame(s).")

    for seat in seats:
        io.prompt(
            f"Press Enter, then speak continuously into '{seat.name}' "
            f"(mic {seat.logical_channel} / DVS input {seat.physical_input}) for {speech_seconds:.0f}s> "
        )
        started = clock()
        while clock() - started < speech_seconds:
            session.add_speech_frame(seat.logical_channel, source.read_observation().levels_db)
            time.sleep(frame_delay)
        io.say(f"  Captured {session.speech_frame_count(seat.logical_channel)} speech frame(s).")

    result = session.result()
    io.say("")
    io.say(render_calibration(result))
    return result


def run_field_setup(config_path: str, *, operator: str, io: WizardIO | None = None, record: FieldRecord | None = None):
    """Drive the guided school field-setup workflow described in the v0.10 brief.

    Returns the FieldRecord used for the session so a caller (or test) can
    inspect what was recorded. Never enables real camera control itself --
    that remains an explicit edit to config/local.yaml plus the existing
    camera_test.bat confirmation prompt.
    """
    io = io or WizardIO()
    record = record or FieldRecord()
    record.set_session(operator=operator)

    io.say("SPEAKERPTZ SCHOOL FIELD SETUP")
    io.say("=" * 72)
    io.say(f"Config: {config_path}")
    io.say(f"Operator: {operator}")
    io.say("Real camera control is never enabled by this workflow.")
    io.say("")

    while True:
        try:
            cfg, _routes = load_config(config_path)
        except ConfigError as exc:
            cfg = None
            io.say(f"CONFIG WARNING: {exc}")

        io.say("")
        io.say("STEPS")
        for letter, key, description in FLOW_STEPS:
            status = record.step_status(key)
            if key in HUMAN_ONLY_STEPS:
                status = StepStatus.HUMAN_CONFIRMED if record.is_confirmed(key) else StepStatus.HUMAN_REQUIRED
            marker = status.value if status else "not started"
            io.say(f"  {letter}) [{marker:24}] {description}")
        io.say("  X) Exit the guided setup")
        choice = io.prompt("Step> ").strip().upper()

        if choice == "X":
            break
        matched = next((row for row in FLOW_STEPS if row[0] == choice), None)
        if matched is None:
            io.say("Unrecognized step letter.")
            continue
        _, key, _description = matched

        if key in {"no_live_meeting", "real_control_off", "physical_joystick", "real_ptz_rehearsal"}:
            answer = io.prompt("Type 'yes' once this has been physically verified> ").strip().lower()
            if answer == "yes":
                record.confirm(key, operator=operator)
                io.say("Recorded.")
            else:
                io.say("Not recorded.")
            continue

        if key == "doctor":
            from speakerptz.runtime.doctor import run_doctor

            code = run_doctor(config_path)
            record.record_step(key, StepStatus.PASS if code == 0 else StepStatus.FAIL)
            continue

        if key == "dante_dvs":
            if cfg is None:
                io.say("Fix the configuration error above first.")
                continue
            from .readiness import _dante_check

            result = _dante_check(cfg)
            record.record_result(result)
            io.say(f"{result.status.value}: {result.detail}")
            continue

        if key == "identify_channels":
            io.say("Run identify_dante_channels.bat in another window (needs a real audio device),")
            io.say("or python -m speakerptz.main --config <path> --identify-channels.")
            continue

        if key == "seat_mapping":
            existing_plan = record.plan
            plan = guided_seat_mapping(
                io, FieldPlan(seats=[SeatAssignment.from_dict(s) for s in existing_plan["seats"]])
                if existing_plan
                else None,
            )
            record.record_plan(plan.to_dict())
            status = StepStatus.PASS if plan.seats else StepStatus.NOT_COMPLETED
            record.record_step(key, status, f"{len(plan.seats)} seat(s) mapped.")
            continue

        if key == "calibration":
            plan_data = record.plan
            if not plan_data or not plan_data.get("seats"):
                io.say("Map seats first (step F).")
                continue
            seats = [SeatAssignment.from_dict(s) for s in plan_data["seats"]]
            simulate = bool(cfg and cfg.get("runtime", {}).get("mode") != "real")
            source_factory = None
            if not simulate and cfg is not None:
                source_factory = _real_source_factory(cfg, len(seats))
            calibration = guided_calibration(cfg or {}, seats, io, source_factory=source_factory)
            record.record_calibration(calibration.to_dict())
            status = StepStatus.PASS if calibration.complete else StepStatus.WARN
            record.record_step(key, status, f"{len(calibration.warnings)} warning(s).")
            continue

        if key == "verify_mics":
            plan_data = record.plan
            if not plan_data:
                io.say("Map seats first (step F).")
                continue
            plan = FieldPlan(
                seats=[SeatAssignment.from_dict(s) for s in plan_data["seats"]],
                wide_shot=WideShotAssignment(**plan_data["wide_shot"]) if plan_data.get("wide_shot") else None,
            )
            cameras = {int(entry["id"]): entry for entry in (cfg or {}).get("cameras") or []}
            results = validate_plan(plan, cameras)
            for result in results:
                io.say(f"  {result.status.value:6} {result.label}: {result.detail}")
            failed = [r for r in results if r.status is StepStatus.FAIL]
            record.record_step(
                key, StepStatus.FAIL if failed else StepStatus.PASS, f"{len(failed)} failing check(s)."
            )
            continue

        if key == "camera_entry":
            if cfg is None:
                io.say("Fix the configuration error above first.")
                continue
            entry = _guided_camera_entry(io)
            if entry is not None:
                updated = set_camera_entry(cfg, entry)
                write_config(config_path, updated)
                io.say(f"Camera {entry['id']} saved to {config_path} (a backup of the prior file was kept).")
                record.record_step(key, StepStatus.PASS, f"Camera {entry['id']} ({entry['driver']}) saved.")
            continue

        if key == "camera_connectivity":
            if cfg is None:
                io.say("Fix the configuration error above first.")
                continue
            summary = check_camera_config(cfg)
            for result in summary:
                io.say(f"  {result.status.value:6} {result.label}: {result.detail}")
            camera_id_text = io.prompt("Probe which camera id? (blank to skip)> ").strip()
            if camera_id_text:
                probe_result = probe_camera(cfg, int(camera_id_text))
                io.say(f"  {probe_result.status.value}: {probe_result.detail}")
                record.record_result(probe_result)
            failed = [r for r in summary if r.status is StepStatus.FAIL]
            record.record_step(key, StepStatus.FAIL if failed else StepStatus.PASS, f"{len(summary)} camera(s) checked.")
            continue

        if key == "manual_preset_check":
            io.say("Run camera_test.bat for the camera being verified.")
            io.say("It requires real_control_enabled: true and a typed confirmation before any movement.")
            continue

        if key in {"preset_mapping", "wide_shot"}:
            plan_data = record.plan
            if not plan_data:
                io.say("Map seats first (step F).")
                continue
            plan = FieldPlan(
                seats=[SeatAssignment.from_dict(s) for s in plan_data["seats"]],
                wide_shot=WideShotAssignment(**plan_data["wide_shot"]) if plan_data.get("wide_shot") else None,
            )
            cameras = {int(entry["id"]): entry for entry in (cfg or {}).get("cameras") or []}
            results = validate_plan(plan, cameras)
            failed = [r for r in results if r.status is StepStatus.FAIL]
            for result in results:
                io.say(f"  {result.status.value:6} {result.label}: {result.detail}")
            if not failed and cfg is not None:
                apply = io.prompt(f"Write this plan to {config_path}? [y/N]> ").strip().lower()
                if apply == "y":
                    updated = apply_plan(cfg, plan)
                    calibration_data = record.calibration
                    if calibration_data:
                        from .calibration import ChannelCalibration, RoomCalibration

                        rc = RoomCalibration(
                            channels=tuple(ChannelCalibration(**row) for row in calibration_data["channels"]),
                            room_noise_floor_db=calibration_data["room_noise_floor_db"],
                            suspected_bleed_pairs=tuple(
                                tuple(pair) for pair in calibration_data["suspected_bleed_pairs"]
                            ),
                            dead_channels=tuple(calibration_data["dead_channels"]),
                            unverified_channels=tuple(calibration_data["unverified_channels"]),
                            recommended=calibration_data["recommended"],
                            warnings=tuple(calibration_data["warnings"]),
                        )
                        updated = apply_calibration(updated, rc)
                    write_config(config_path, updated)
                    io.say(f"Saved to {config_path} (a timestamped backup of the prior file was kept).")
            record.record_step(key, StepStatus.FAIL if failed else StepStatus.PASS, f"{len(failed)} failing check(s).")
            continue

        if key == "dry_run":
            io.say("Run run_school_dry_run.bat in another window for a live audio dry run,")
            io.say("or run_simulation.bat for a fully simulated dry run.")
            io.say("Neither can transmit real camera commands.")
            continue

        if key in {"rehearsal", "rehearsal_edge_cases"}:
            results = run_automated_scenarios()
            io.say(render_rehearsal(results))
            failed = [r for r in results.values() if r.status is StepStatus.FAIL]
            record.record_step(
                "dry_run_rehearsal", StepStatus.FAIL if failed else StepStatus.PASS, f"{len(failed)} failing scenario(s)."
            )
            record.record_step(key, StepStatus.FAIL if failed else StepStatus.PASS, f"{len(failed)} failing scenario(s).")
            if key == "rehearsal_edge_cases":
                io.say("")
                io.say("With a person at the keyboard/dashboard: confirm AUTO off, manual preset keys (1-9),")
                io.say("W (wide), and X (emergency stop) all work as expected during this rehearsal.")
                answer = io.prompt("Type 'yes' once manual override has been physically verified> ").strip().lower()
                if answer == "yes":
                    record.confirm("manual_override", operator=operator)
                    io.say("Recorded.")
                else:
                    io.say("Not recorded.")
            continue

        if key == "readiness_report":
            report = build_readiness_report(config_path, field_record=record)
            text = render_readiness(report)
            io.say(text)
            record.data["last_report"] = report.to_dict()
            record.save()
            continue

    return record


def _guided_camera_entry(io: WizardIO) -> dict | None:
    io.say("")
    io.say("CAMERA ENTRY")
    id_text = io.prompt("Camera id (integer)> ").strip()
    if not id_text:
        return None
    name = io.prompt("Camera name> ").strip() or f"Camera {id_text}"
    driver = io.prompt("Driver [simulator/visca/onvif]> ").strip().lower() or "simulator"
    entry = {"id": int(id_text), "name": name, "driver": driver, "enabled": True}
    if driver in {"visca", "onvif"}:
        entry["host"] = io.prompt("Camera IP address> ").strip()
        port_text = io.prompt("Port (blank for default)> ").strip()
        if port_text:
            entry["port"] = int(port_text)
        if driver == "onvif":
            entry["username"] = io.prompt("ONVIF username> ").strip()
            entry["password_env"] = io.prompt(
                "Environment variable holding the password (e.g. SPEAKERPTZ_CAMERA_1_PASSWORD)> "
            ).strip()
    return entry


def _real_source_factory(cfg: dict, channels: int):
    from speakerptz.audio.channelmap import required_physical_channels
    from speakerptz.audio.devices import resolve_input_device
    from speakerptz.audio.realtime import RealAudioSource

    runtime = cfg.get("runtime", {})
    audio = cfg.get("audio", {})
    channel_map = normalize_channel_map(audio.get("channel_map"), channels) if audio.get("channel_map") else list(
        range(1, channels + 1)
    )
    physical_needed = required_physical_channels(channel_map)
    match = resolve_input_device(
        device_index=runtime.get("device_index"),
        device_name=runtime.get("device_name"),
        channels=physical_needed,
        hostapi_name=runtime.get("hostapi_name"),
    )
    sample_rate = int(audio.get("sample_rate", 48000))

    def factory():
        source = RealAudioSource(match.index, channels, sample_rate, channel_map=channel_map)
        source.start()
        return source

    return factory
