from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time

from .audio.simulator import SimulatedAudioSource
from .audio.channelmap import normalize_channel_map, required_physical_channels
from .audio.devices import resolve_input_device
from .cameras.manager import CameraManager
from .cameras.models import CameraState
from .cameras.base import CameraConnectionError
from .core.config import load_config, ConfigError
from .core.detector import ActiveSpeakerDetector
from .runtime.logging import setup_logging, event as log_event
from .runtime.instance import InstanceLock, InstanceLockError
from .runtime.state import RuntimeState
from .ui.dashboard import DashboardCommand, DashboardServer, DashboardState


VERSION = "0.10"


class ConsoleControls:
    """Small Windows-console manual override layer; safely no-ops elsewhere."""

    def poll(self):
        if os.name != "nt":
            return None
        try:
            import msvcrt
            if not msvcrt.kbhit():
                return None
            return msvcrt.getwch().lower()
        except Exception:
            return None


def render(
    levels,
    detector,
    routes,
    mode,
    auto_enabled,
    camera,
    device_label="",
    channel_map=None,
    audio_warning="",
    dashboard_url="",
):
    os.system("cls" if os.name == "nt" else "clear")
    snap = detector.snapshot()
    print(f"SPEAKERPTZ v{VERSION}")
    print("=" * 104)

    if snap.calibrating:
        print(f"CALIBRATING ROOM NOISE: {snap.calibration_remaining:0.1f}s remaining - stay quiet")
        print("-" * 104)

    channel_map = channel_map or list(range(1, len(levels) + 1))
    for idx, db in enumerate(levels, start=1):
        route = routes.get(idx)
        name = route.name if route else f"Mic {idx}"
        physical = channel_map[idx - 1] if idx - 1 < len(channel_map) else idx
        bars = max(0, min(24, int((db + 70) / 2)))
        floor = snap.noise_floors[idx - 1] if idx - 1 < len(snap.noise_floors) else None
        snr = snap.snr_db[idx - 1] if idx - 1 < len(snap.snr_db) else None
        speech = snap.speech_probabilities[idx - 1] if idx - 1 < len(snap.speech_probabilities) else None
        marker = "  < ACTIVE" if detector.active == idx else ""
        floor_text = f"floor {floor:6.1f}" if floor is not None else "floor   --.-"
        snr_text = f"+{snr:4.1f}" if snr is not None and snr >= 0 else (f"{snr:5.1f}" if snr is not None else "  --.-")
        print(
            f"MIC {idx:02d} <- IN {physical:02d} | {name[:18]:18} {db:6.1f} dB | "
            f"{floor_text} | SNR {snr_text} | VAD {speech * 100:5.1f}% | {'#' * bars}{marker}"
            if speech is not None
            else f"MIC {idx:02d} <- IN {physical:02d} | {name[:18]:18} {db:6.1f} dB | "
            f"{floor_text} | SNR {snr_text} | VAD   --.-% | {'#' * bars}{marker}"
        )

    print()
    if detector.active and detector.active in routes:
        r = routes[detector.active]
        print(f"ACTIVE SPEAKER: {r.name} | CAM {r.camera} PRESET {r.preset}")
    elif detector.active:
        print(f"ACTIVE SPEAKER: MIC {detector.active}")
    else:
        print("ACTIVE SPEAKER: NONE")

    print(f"CONFIDENCE: {detector.confidence * 100:5.1f}%")
    print(f"DETECTOR: {snap.reason}")
    print(f"AUTO DIRECTOR: {'ON' if auto_enabled else 'OFF / MANUAL'}")
    print(f"MODE: {mode}")
    if device_label:
        print(f"AUDIO DEVICE: {device_label}")
    if audio_warning:
        print(f"AUDIO FAIL-SAFE: {audio_warning}")
    print(f"CAMERA CONTROL: {camera.mode_banner}")
    if camera.emergency_stopped:
        print("CAMERA SAFETY: EMERGENCY STOP LATCHED - PRESS R TO RESET; AUTO STAYS OFF")
    for camera_id, health in camera.health_all().items():
        detail = f" | {health.message}" if health.message else ""
        print(f"CAM {camera_id}: {health.state.value.upper()}{detail}")
    print(f"LAST CAMERA REQUEST: {camera.last_action}")
    if dashboard_url:
        print(f"OPERATOR DASHBOARD: {dashboard_url}")
    print("LOGGING: ON -> logs\\speakerptz-YYYYMMDD.log")
    print()
    print("HOTKEYS: A = auto on/off | X = EMERGENCY STOP | R = reset stop | W = wide | 1-9 = manual | Q = quit")


def _require_explicit_real_camera_mode(cfg: dict, manager: CameraManager, camera_id: int, operation: str) -> None:
    if not bool(cfg.get("real_control_enabled", False)):
        raise SystemExit(
            f"{operation} BLOCKED: real_control_enabled is false. Configure the exact camera first, "
            "then deliberately enable real control in config/local.yaml."
        )
    camera_cfg = manager.configs.get(int(camera_id))
    if camera_cfg is None:
        raise SystemExit(f"{operation} BLOCKED: camera {camera_id} is not configured.")
    if not camera_cfg.enabled:
        raise SystemExit(f"{operation} BLOCKED: camera {camera_id} is disabled.")
    if not camera_cfg.is_real:
        raise SystemExit(f"{operation} BLOCKED: camera {camera_id} still uses the simulator driver.")


def run_camera_probe(cfg: dict, manager: CameraManager, camera_id: int) -> int:
    _require_explicit_real_camera_mode(cfg, manager, camera_id, "CAMERA PROBE")
    camera_cfg = manager.configs[int(camera_id)]
    print("SPEAKERPTZ SINGLE-CAMERA PROBE")
    print("=" * 72)
    print(f"Camera {camera_cfg.id}: {camera_cfg.name}")
    print(f"Protocol: {camera_cfg.driver.upper()} | Endpoint: {camera_cfg.host}:{camera_cfg.port}")
    print("This is a bounded check of this one configured endpoint; no network scan is performed.")
    health = manager.connect(int(camera_id))
    print(f"RESULT: {health.state.value.upper()} - {health.message or health.last_error or ''}")
    manager.disconnect_all()
    return 0 if health.ok else 1


def run_camera_test(cfg: dict, manager: CameraManager, camera_id: int) -> int:
    _require_explicit_real_camera_mode(cfg, manager, camera_id, "CAMERA TEST")
    health = manager.connect(int(camera_id))
    if not health.ok:
        print(f"CAMERA TEST FAILED: {health.last_error or health.message}")
        manager.disconnect_all()
        return 1
    phrase = f"MOVE CAMERA {int(camera_id)}"
    print("REAL PTZ CONTROL TEST")
    print("=" * 72)
    print(f"Type exactly {phrase!r} to unlock manual movement. Anything else exits safely.")
    if input("> ").strip() != phrase:
        print("Confirmation did not match. No movement command was sent.")
        manager.disconnect_all()
        return 1

    wide = cfg["wide_shot"]
    print("Commands: P <preset> | W (configured wide, if on this camera) | H (home) | S (stop) | Q")
    try:
        while True:
            command = input("camera-test> ").strip().lower()
            if command in {"q", "quit", "exit"}:
                break
            if command in {"s", "stop"}:
                result = manager.stop(camera_id)
            elif command in {"h", "home"}:
                result = manager.home(camera_id)
            elif command in {"w", "wide"}:
                if int(wide["camera"]) != int(camera_id):
                    print("Configured wide shot belongs to a different camera.")
                    continue
                result = manager.goto_preset(camera_id, int(wide["preset"]), "Wide test", force=True)
            elif command.startswith("p "):
                try:
                    preset = int(command.split(maxsplit=1)[1])
                except ValueError:
                    print("Preset must be an integer.")
                    continue
                result = manager.goto_preset(camera_id, preset, "Manual test", force=True)
            else:
                print("Unknown command. Use P <preset>, W, H, S, or Q.")
                continue
            print("OK" if result.accepted else f"BLOCKED/FAILED: {result.reason}")
    finally:
        manager.stop(camera_id)
        manager.disconnect_all()
    return 0


def build_detector(audio_cfg, now=None):
    return ActiveSpeakerDetector(
        absolute_threshold_db=float(audio_cfg.get("absolute_threshold_db", -50.0)),
        signal_margin_db=float(audio_cfg.get("signal_margin_db", 8.0)),
        dominance_margin_db=float(audio_cfg.get("dominance_margin_db", 3.0)),
        initial_activation_ms=int(audio_cfg.get("initial_activation_ms", 250)),
        switch_delay_ms=int(audio_cfg.get("switch_delay_ms", 650)),
        hold_time_ms=int(audio_cfg.get("hold_time_ms", 1200)),
        silence_timeout_ms=int(audio_cfg.get("silence_timeout_ms", 5000)),
        calibration_seconds=float(audio_cfg.get("calibration_seconds", 3.0)),
        confidence_min=float(audio_cfg.get("confidence_min", 0.55)),
        vad_enabled=bool(audio_cfg.get("vad_enabled", True)),
        vad_threshold=float(audio_cfg.get("vad_threshold", 0.55)),
        vad_weight=float(audio_cfg.get("vad_weight", 0.45)),
        confidence_smoothing=float(audio_cfg.get("confidence_smoothing", 0.35)),
        transient_rejection_ms=int(audio_cfg.get("transient_rejection_ms", 180)),
        overlap_margin_db=float(audio_cfg.get("overlap_margin_db", 2.0)),
        adaptive_noise_enabled=bool(audio_cfg.get("adaptive_noise_enabled", True)),
        adaptive_noise_alpha=float(audio_cfg.get("adaptive_noise_alpha", 0.02)),
        noise_floor_min_db=float(audio_cfg.get("noise_floor_min_db", -85.0)),
        noise_floor_max_db=float(audio_cfg.get("noise_floor_max_db", -35.0)),
        disabled_channels=audio_cfg.get("disabled_channels", []),
        level_offsets_db=audio_cfg.get("level_offsets_db", []),
        bleed_pairs=audio_cfg.get("bleed_pairs", []),
        bleed_rejection_db=float(audio_cfg.get("bleed_rejection_db", 6.0)),
        now=now,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/room.yaml")
    parser.add_argument("--simulate", action="store_true", help="Use simulated multichannel audio")
    parser.add_argument("--device", type=int, help="sounddevice input device index for real-audio mode")
    parser.add_argument("--device-name", help="case-insensitive substring of Windows audio input device name")
    parser.add_argument("--channels", type=int, help="Override logical input channel count")
    parser.add_argument("--list-devices", action="store_true", help="Print audio devices and exit")
    parser.add_argument("--doctor", action="store_true", help="Run startup self-test and exit")
    parser.add_argument("--identify-channels", action="store_true", help="Meter raw physical inputs to identify DVS/Dante channel numbers")
    parser.add_argument("--identify-count", type=int, help="Physical input count to open in identifier mode")
    parser.add_argument("--camera-probe", type=int, metavar="ID", help="Safely probe one configured camera endpoint and exit")
    parser.add_argument("--camera-test", type=int, metavar="ID", help="Explicit interactive manual test for one real camera")
    parser.add_argument("--no-dashboard", action="store_true", help="Disable the configured localhost dashboard")
    parser.add_argument("--dashboard-port", type=int, help="Override the configured localhost dashboard port")
    parser.add_argument("--soak-test", action="store_true", help="Run bounded synthetic resilience test and exit")
    parser.add_argument("--soak-iterations", type=int, default=5000, help="Synthetic frames for --soak-test")
    parser.add_argument("--soak-seed", type=int, default=17, help="Deterministic seed for --soak-test")
    parser.add_argument("--field-setup", action="store_true", help="Run the guided school field-setup workflow")
    parser.add_argument("--calibrate", action="store_true", help="Run guided per-mic room calibration and exit")
    parser.add_argument("--field-readiness", action="store_true", help="Print the field readiness report and exit")
    parser.add_argument("--rehearsal-check", action="store_true", help="Run automated rehearsal scenarios and exit")
    parser.add_argument("--field-confirm", metavar="KEY", help="Record a human-verified confirmation and exit")
    parser.add_argument("--field-note", default="", help="Optional note attached to --field-confirm")
    parser.add_argument("--operator", default="", help="Operator name recorded with field-tool actions")
    parser.add_argument(
        "--field-record",
        default="logs/field-setup.json",
        help="Path to the local field-setup journal (Git-ignored)",
    )
    args = parser.parse_args()

    if args.soak_test:
        from .runtime.soak import run_soak_test

        summary = run_soak_test(args.soak_iterations, seed=args.soak_seed)
        print(json.dumps(summary, indent=2, sort_keys=True))
        raise SystemExit(0 if summary["passed"] else 7)

    if args.list_devices:
        from .audio.devices import list_input_devices
        for d in list_input_devices():
            api = f" | {d.hostapi_name}" if d.hostapi_name else ""
            print(f"{d.index:>3} | {d.max_input_channels:>2} in | {d.name}{api}")
        return

    if args.doctor:
        from .runtime.doctor import run_doctor
        raise SystemExit(run_doctor(args.config))

    if args.rehearsal_check:
        from .field.rehearsal import render_rehearsal, run_automated_scenarios
        from .field.record import FieldRecord
        from .field.models import StepStatus

        results = run_automated_scenarios()
        print(render_rehearsal(results))
        record = FieldRecord(args.field_record)
        if args.operator:
            record.set_session(operator=args.operator)
        failed = [result for result in results.values() if result.status is StepStatus.FAIL]
        for result in results.values():
            record.record_result(result)
        record.record_step(
            "dry_run_rehearsal",
            StepStatus.FAIL if failed else StepStatus.PASS,
            f"{len(failed)} failing scenario(s).",
        )
        raise SystemExit(0 if not failed else 1)

    if args.field_confirm:
        from .field.models import CONFIRMABLE_KEYS
        from .field.record import FieldRecord

        if args.field_confirm not in CONFIRMABLE_KEYS:
            accepted = ", ".join(sorted(CONFIRMABLE_KEYS))
            raise SystemExit(f"FIELD CONFIRM ERROR: unknown key '{args.field_confirm}'. Accepted values: {accepted}.")
        if not args.operator:
            raise SystemExit("FIELD CONFIRM ERROR: --operator is required for a human confirmation.")
        record = FieldRecord(args.field_record)
        try:
            record.confirm(args.field_confirm, operator=args.operator, note=args.field_note)
        except ValueError as exc:
            raise SystemExit(f"FIELD CONFIRM ERROR: {exc}")
        print(f"Recorded human confirmation for '{args.field_confirm}' by {args.operator}.")
        return

    try:
        cfg, routes = load_config(args.config)
    except ConfigError as exc:
        raise SystemExit(f"CONFIG ERROR: {exc}")

    audio_cfg = cfg["audio"]
    runtime_cfg = cfg.get("runtime", {})
    channels = int(args.channels or audio_cfg["channels"])
    sample_rate = int(audio_cfg.get("sample_rate", 48000))
    channel_map = normalize_channel_map(audio_cfg.get("channel_map"), channels)
    physical_needed = required_physical_channels(channel_map)

    requested_sim = args.simulate or runtime_cfg.get("mode", "real") == "simulate"
    device_index = args.device if args.device is not None else runtime_cfg.get("device_index")
    device_name = args.device_name or runtime_cfg.get("device_name")
    hostapi_name = runtime_cfg.get("hostapi_name")

    instance_lock = InstanceLock(str(runtime_cfg.get("instance_lock_file", "logs/speakerptz.lock")))
    try:
        instance_lock.acquire()
    except InstanceLockError as exc:
        raise SystemExit(f"INSTANCE ERROR: {exc}")

    logger = setup_logging(str(runtime_cfg.get("log_dir", "logs")))
    try:
        camera = CameraManager.from_config(cfg, logger=logger)
    except CameraConnectionError as exc:
        instance_lock.release()
        raise SystemExit(f"CAMERA CONFIGURATION ERROR: {exc}")

    if args.camera_probe is not None:
        try:
            raise SystemExit(run_camera_probe(cfg, camera, args.camera_probe))
        finally:
            instance_lock.release()
    if args.camera_test is not None:
        try:
            raise SystemExit(run_camera_test(cfg, camera, args.camera_test))
        finally:
            instance_lock.release()

    if args.identify_channels:
        if requested_sim:
            raise SystemExit("CHANNEL IDENTIFIER requires a real audio device; set runtime.mode: real.")
        count = int(args.identify_count or audio_cfg.get("identifier_channels") or physical_needed)
        try:
            match = resolve_input_device(
                device_index=device_index,
                device_name=device_name,
                channels=count,
                hostapi_name=hostapi_name,
            )
            import sounddevice as sd
            sd.check_input_settings(device=match.index, channels=count, samplerate=sample_rate)
        except Exception as exc:
            raise SystemExit(f"AUDIO DEVICE ERROR: {exc}")
        from .audio.identifier import run_identifier
        try:
            run_identifier(match.index, count, sample_rate, f"{match.index} | {match.name}")
            return
        finally:
            instance_lock.release()

    if args.field_readiness:
        from .field.readiness import build_readiness_report, render_readiness
        from .field.record import FieldRecord

        try:
            report = build_readiness_report(args.config, field_record=FieldRecord(args.field_record))
            print(render_readiness(report))
            raise SystemExit(0 if report.ready_for_hardware_rehearsal else 1)
        finally:
            instance_lock.release()

    if args.calibrate:
        from .field.mapping import plan_from_config
        from .field.models import StepStatus
        from .field.record import FieldRecord
        from .field.wizard import WizardIO, guided_calibration, real_source_factory

        try:
            if requested_sim:
                raise SystemExit("CALIBRATION requires a real audio device; set runtime.mode: real or use --field-setup for a simulated rehearsal of this step.")
            plan = plan_from_config(cfg)
            if not plan.seats:
                raise SystemExit("CALIBRATION requires people/seats to already be mapped in configuration.")
            io = WizardIO()
            calibration = guided_calibration(
                cfg, plan.seats, io, source_factory=real_source_factory(cfg, len(plan.seats))
            )
            record = FieldRecord(args.field_record)
            if args.operator:
                record.set_session(operator=args.operator)
            record.record_calibration(calibration.to_dict())
            status = StepStatus.PASS if calibration.complete else StepStatus.WARN
            record.record_step("mic_calibration", status, f"{len(calibration.warnings)} warning(s).")
            raise SystemExit(0 if calibration.complete else 1)
        finally:
            instance_lock.release()

    if args.field_setup:
        from .field.record import FieldRecord
        from .field.wizard import WizardIO, run_field_setup

        try:
            operator = args.operator or input("Operator name for this setup session> ").strip()
            if not operator:
                raise SystemExit("FIELD SETUP ERROR: an operator name is required.")
            run_field_setup(args.config, operator=operator, io=WizardIO(), record=FieldRecord(args.field_record))
            return
        finally:
            instance_lock.release()

    detector = build_detector(audio_cfg)
    wide = cfg["wide_shot"]
    controls = ConsoleControls()
    device_label = ""
    audio_warning = ""
    stale_logged = False
    dashboard_state: DashboardState | None = None
    dashboard_server: DashboardServer | None = None
    dashboard_url = ""

    if requested_sim:
        source = SimulatedAudioSource(channels)
        mode = "SIMULATION"
        needs_stop = False
        log_event(logger, "startup", version=VERSION, mode=mode, channels=channels, channel_map=channel_map)
    else:
        import sounddevice as sd
        from .audio.realtime import RealAudioSource
        try:
            match = resolve_input_device(
                device_index=device_index,
                device_name=device_name,
                channels=physical_needed,
                hostapi_name=hostapi_name,
            )
            sd.check_input_settings(device=match.index, channels=physical_needed, samplerate=sample_rate)
        except Exception as exc:
            raise SystemExit(f"AUDIO DEVICE ERROR: {exc}\nRun: .venv\\Scripts\\python.exe -m speakerptz.main --list-devices")
        source = RealAudioSource(match.index, channels, sample_rate, channel_map=channel_map)
        source.start()
        mode = f"REAL AUDIO | {channels} LOGICAL CH / {physical_needed} PHYSICAL CH @ {sample_rate} Hz"
        device_label = f"{match.index} | {match.name}"
        needs_stop = True
        log_event(
            logger,
            "startup",
            version=VERSION,
            mode=mode,
            device_index=match.index,
            device_name=match.name,
            channels=channels,
            channel_map=channel_map,
        )

    camera_health = camera.connect_all()
    cameras_ready = all(health.ok or health.state == CameraState.DISABLED for health in camera_health.values())
    # Real mode is deliberately re-armed by the operator on every launch. A
    # persistent config file alone can never make AUTO start moving cameras.
    auto_enabled = (
        bool(runtime_cfg.get("auto_start", True))
        and cameras_ready
        and not camera.real_control_enabled
    )
    log_event(
        logger,
        "camera_runtime_ready",
        mode=camera.mode_banner,
        auto_enabled=auto_enabled,
        camera_states={camera_id: health.state.value for camera_id, health in camera_health.items()},
    )
    runtime_state = RuntimeState(str(runtime_cfg.get("state_file", "logs/runtime-state.json")))
    previous_unclean = runtime_state.previous_unclean_shutdown
    state_warning = "Previous SPEAKERPTZ run did not record a clean shutdown" if previous_unclean else ""
    last_heartbeat = 0.0
    last_health_check = 0.0
    last_audio_reconnect = 0.0
    audio_reconnect_attempts = 0
    observed_callback_count = getattr(source, "callback_count", 0)

    def dashboard_command(command: DashboardCommand) -> None:
        nonlocal auto_enabled
        action = command.action
        accepted = True
        message = ""
        if action in {"auto_toggle", "auto_on"}:
            requested_on = not auto_enabled if action == "auto_toggle" else True
            healthy = all(h.ok for h in camera.health_all().values() if h.state != CameraState.DISABLED)
            if requested_on and (camera.emergency_stopped or not healthy):
                auto_enabled = False
                accepted = False
                message = "AUTO blocked by emergency stop or camera health."
            else:
                auto_enabled = requested_on
                message = f"AUTO {'enabled' if auto_enabled else 'disabled'}"
            log_event(logger, "auto_director", enabled=auto_enabled, source="dashboard", accepted=accepted)
        elif action == "auto_off":
            auto_enabled = False
            message = "AUTO disabled"
            log_event(logger, "auto_director", enabled=False, source="dashboard", accepted=True)
        elif action == "emergency_stop":
            auto_enabled = False
            camera.emergency_stop()
            message = "Emergency stop latched"
            log_event(logger, "operator_emergency_stop", source="dashboard")
        elif action == "reset_stop":
            auto_enabled = False
            camera.clear_emergency_stop()
            message = "Emergency stop cleared; AUTO remains off"
            log_event(logger, "operator_emergency_stop_reset", source="dashboard")
        elif action == "wide":
            result = camera.goto_preset(int(wide["camera"]), int(wide["preset"]), "Wide shot (dashboard)")
            accepted = result.accepted
            message = "Wide shot requested" if accepted else result.reason
            log_event(logger, "camera_request", source="dashboard", camera=int(wide["camera"]), preset=int(wide["preset"]), label="Wide shot", accepted=accepted, reason=result.reason)
        elif action == "manual_preset":
            auto_enabled = False
            result = camera.goto_preset(int(command.camera_id), int(command.preset), "Dashboard manual")
            accepted = result.accepted
            message = "Manual preset requested" if accepted else result.reason
            log_event(logger, "camera_request", source="dashboard", camera=command.camera_id, preset=command.preset, label="Manual preset", accepted=accepted, reason=result.reason)
        if dashboard_state is not None:
            dashboard_state.add_event(
                "operator_command",
                f"{action}: {message}",
                accepted=accepted,
            )

    running = True
    prior_signal_handlers = {}

    def request_shutdown(signum, _frame):
        nonlocal running
        running = False
        log_event(logger, "shutdown_requested", signal=signum)

    shutdown_signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        shutdown_signals.append(signal.SIGBREAK)
    for shutdown_signal in shutdown_signals:
        try:
            prior_signal_handlers[shutdown_signal] = signal.getsignal(shutdown_signal)
            signal.signal(shutdown_signal, request_shutdown)
        except (ValueError, OSError):
            # Signal registration is only available in the main interpreter
            # thread and varies slightly across supported platforms.
            pass
    try:
        runtime_state.mark_started(VERSION, camera.mode_banner)
        if previous_unclean:
            log_event(logger, "previous_unclean_shutdown")
        dashboard_cfg = cfg.get("dashboard", {})
        if bool(dashboard_cfg.get("enabled", False)) and not args.no_dashboard:
            dashboard_state = DashboardState()
            dashboard_state.update(
                version=VERSION,
                mode_banner=camera.mode_banner,
                real_control_enabled=camera.real_control_enabled,
                auto_enabled=auto_enabled,
                emergency_stopped=camera.emergency_stopped,
            )
            dashboard_server = DashboardServer(
                dashboard_state,
                str(dashboard_cfg.get("host", "127.0.0.1")),
                int(args.dashboard_port or dashboard_cfg.get("port", 8765)),
            )
            try:
                dashboard_url = dashboard_server.start()
            except OSError as exc:
                raise SystemExit(f"DASHBOARD STARTUP ERROR: {exc}") from exc
            dashboard_state.add_event("startup", f"Dashboard listening at {dashboard_url}")
            log_event(logger, "dashboard_started", url=dashboard_url)
        while running:
            loop_now = time.monotonic()
            key = controls.poll()
            if key == "q":
                running = False
                continue
            if key == "a":
                if camera.emergency_stopped:
                    auto_enabled = False
                elif all(h.ok for h in camera.health_all().values() if h.state != CameraState.DISABLED):
                    auto_enabled = not auto_enabled
                else:
                    auto_enabled = False
                log_event(logger, "auto_director", enabled=auto_enabled)
            elif key == "x":
                auto_enabled = False
                camera.emergency_stop()
                log_event(logger, "operator_emergency_stop")
            elif key == "r":
                auto_enabled = False
                camera.clear_emergency_stop()
                log_event(logger, "operator_emergency_stop_reset")
            elif key == "w":
                result = camera.goto_preset(int(wide["camera"]), int(wide["preset"]), "Wide shot (manual)")
                log_event(logger, "camera_request", source="manual", camera=int(wide["camera"]), preset=int(wide["preset"]), label="Wide shot", accepted=result.accepted, reason=result.reason)
            elif key and key.isdigit() and key != "0":
                channel = int(key)
                if channel in routes:
                    auto_enabled = False
                    r = routes[channel]
                    result = camera.goto_preset(r.camera, r.preset, f"{r.name} (manual)")
                    log_event(logger, "camera_request", source="manual", mic_channel=channel, camera=r.camera, preset=r.preset, label=r.name, accepted=result.accepted, reason=result.reason)

            if dashboard_state is not None:
                for command in dashboard_state.drain_commands():
                    dashboard_command(command)

            if loop_now - last_health_check >= float(runtime_cfg.get("health_check_seconds", 1.0)):
                last_health_check = loop_now
                maintained = camera.maintain_health()
                unhealthy = [
                    camera_id
                    for camera_id, health in maintained.items()
                    if health.state != CameraState.DISABLED and not health.ok
                ]
                if unhealthy and not camera.emergency_stopped:
                    auto_enabled = False
                    camera.emergency_stop()
                    log_event(logger, "camera_health_fail_safe", camera_ids=unhealthy)
                    if dashboard_state is not None:
                        dashboard_state.add_event(
                            "camera_health_fail_safe",
                            f"Camera health failure {unhealthy}; AUTO off and STOP latched",
                        )

            if hasattr(source, "read_observation"):
                observation = source.read_observation()
                levels = observation.levels_db
                speech_probabilities = observation.speech_probabilities
            else:
                levels = source.read_levels()
                speech_probabilities = None
            audio_ok = True
            audio_warning = ""
            if needs_stop:
                health = source.health(float(runtime_cfg.get("audio_stale_seconds", 1.5)))
                if not health.ok:
                    audio_ok = False
                    audio_warning = f"PAUSED - no audio callback for {health.stale_seconds:.1f}s"
                    if auto_enabled:
                        auto_enabled = False
                    if not stale_logged:
                        camera.emergency_stop()
                        log_event(logger, "audio_stale", seconds=round(health.stale_seconds, 3), status=health.callback_status)
                        if dashboard_state is not None:
                            dashboard_state.add_event("audio_stale", audio_warning)
                        stale_logged = True
                    reconnect_limit = int(runtime_cfg.get("audio_reconnect_attempts", 3))
                    reconnect_interval = float(runtime_cfg.get("audio_reconnect_interval_seconds", 2.0))
                    if (
                        audio_reconnect_attempts < reconnect_limit
                        and loop_now - last_audio_reconnect >= reconnect_interval
                    ):
                        last_audio_reconnect = loop_now
                        audio_reconnect_attempts += 1
                        try:
                            source.restart()
                            log_event(logger, "audio_reconnect_attempt", attempt=audio_reconnect_attempts, started=True)
                        except Exception as exc:
                            log_event(logger, "audio_reconnect_attempt", attempt=audio_reconnect_attempts, started=False, error=str(exc))
                else:
                    if stale_logged:
                        log_event(logger, "audio_recovered")
                        if dashboard_state is not None:
                            dashboard_state.add_event("audio_recovered", "Audio callback recovered; AUTO remains off")
                    stale_logged = False
                    callback_count = getattr(source, "callback_count", observed_callback_count)
                    if callback_count > observed_callback_count:
                        observed_callback_count = callback_count
                        audio_reconnect_attempts = 0
                    if health.callback_status:
                        audio_warning = health.callback_status

            event = (
                detector.update(levels, speech_probabilities=speech_probabilities)
                if audio_ok
                else None
            )
            if auto_enabled and event:
                kind, channel = event
                if kind == "speaker" and channel in routes:
                    r = routes[channel]
                    result = camera.goto_preset(r.camera, r.preset, r.name)
                    log_event(logger, "speaker_change", mic_channel=channel, name=r.name, confidence=round(detector.confidence, 4), detector_reason=detector.reason, camera=r.camera, preset=r.preset, accepted=result.accepted, reason=result.reason)
                    if dashboard_state is not None:
                        dashboard_state.add_event("speaker_change", f"{r.name} -> camera {r.camera} preset {r.preset}", accepted=result.accepted)
                elif kind == "silence":
                    result = camera.goto_preset(int(wide["camera"]), int(wide["preset"]), "Wide shot")
                    log_event(logger, "silence_wide", detector_reason=detector.reason, camera=int(wide["camera"]), preset=int(wide["preset"]), accepted=result.accepted, reason=result.reason)
                    if dashboard_state is not None:
                        dashboard_state.add_event("silence_wide", "Silence timeout -> wide shot", accepted=result.accepted)

            if dashboard_state is not None:
                snapshot = detector.snapshot()
                health_rows = camera.health_all()
                warnings = []
                if camera.real_control_enabled:
                    warnings.append("REAL PTZ CONTROL ENABLED")
                if state_warning:
                    warnings.append(state_warning)
                if camera.emergency_stopped:
                    warnings.append("EMERGENCY STOP IS LATCHED")
                if audio_warning:
                    warnings.append(audio_warning)
                for camera_id, camera_health in health_rows.items():
                    if camera_health.state not in {CameraState.READY, CameraState.DISABLED}:
                        warnings.append(f"Camera {camera_id}: {camera_health.state.value}")

                meters = []
                for index, level in enumerate(levels):
                    channel = index + 1
                    route = routes.get(channel)
                    meters.append(
                        {
                            "channel": channel,
                            "physical_input": channel_map[index] if index < len(channel_map) else channel,
                            "name": route.name if route else f"Mic {channel}",
                            "level_db": round(float(level), 2),
                            "noise_floor_db": round(snapshot.noise_floors[index], 2) if index < len(snapshot.noise_floors) else None,
                            "snr_db": round(snapshot.snr_db[index], 2) if index < len(snapshot.snr_db) else None,
                            "speech_probability": round(snapshot.speech_probabilities[index], 4) if index < len(snapshot.speech_probabilities) else 0.0,
                            "eligible": bool(snapshot.eligible[index]) if index < len(snapshot.eligible) else False,
                        }
                    )

                active_route = routes.get(snapshot.active) if snapshot.active else None
                candidate_route = routes.get(snapshot.candidate) if snapshot.candidate else None
                if requested_sim:
                    dante_status = "SIMULATED / NOT CONNECTED"
                elif "dante" in device_label.lower() and audio_ok:
                    dante_status = "CONNECTED"
                elif audio_ok:
                    dante_status = "AUDIO ACTIVE; DANTE NAME NOT CONFIRMED"
                else:
                    dante_status = "NOT READY"

                dashboard_state.update(
                    version=VERSION,
                    mode_banner=camera.mode_banner,
                    real_control_enabled=camera.real_control_enabled,
                    auto_enabled=auto_enabled,
                    emergency_stopped=camera.emergency_stopped,
                    active_speaker=(
                        {"channel": snapshot.active, "name": active_route.name}
                        if snapshot.active and active_route
                        else ({"channel": snapshot.active, "name": f"Mic {snapshot.active}"} if snapshot.active else None)
                    ),
                    candidate_speaker=(
                        {"channel": snapshot.candidate, "name": candidate_route.name}
                        if snapshot.candidate and candidate_route
                        else ({"channel": snapshot.candidate, "name": f"Mic {snapshot.candidate}"} if snapshot.candidate else None)
                    ),
                    confidence=round(snapshot.confidence, 4),
                    detector_reason=snapshot.reason,
                    meters=meters,
                    audio={
                        "ok": audio_ok,
                        "device": device_label or "Simulated multichannel audio",
                        "warning": audio_warning,
                        "dante_status": dante_status,
                    },
                    cameras=[
                        {
                            "id": camera_id,
                            "name": camera.configs[camera_id].name,
                            "state": camera_health.state.value.upper(),
                            "message": camera_health.message or camera_health.last_error or "",
                        }
                        for camera_id, camera_health in health_rows.items()
                    ],
                    current_camera_presets=camera.current_presets,
                    last_camera_request=camera.last_action,
                    warnings=warnings,
                )

            if loop_now - last_heartbeat >= float(runtime_cfg.get("heartbeat_seconds", 5.0)):
                last_heartbeat = loop_now
                try:
                    runtime_state.heartbeat(
                        auto_enabled=auto_enabled,
                        audio_ok=audio_ok,
                        camera_states={camera_id: health.state.value for camera_id, health in camera.health_all().items()},
                    )
                except OSError as exc:
                    state_warning = f"Runtime heartbeat write failed: {exc}"
                    log_event(logger, "heartbeat_write_failed", error=str(exc))

            render(levels, detector, routes, mode, auto_enabled, camera, device_label, channel_map, audio_warning, dashboard_url)
            time.sleep(0.1)
    except KeyboardInterrupt:
        log_event(logger, "shutdown_requested", signal="KeyboardInterrupt")
    finally:
        for shutdown_signal, previous_handler in prior_signal_handlers.items():
            try:
                signal.signal(shutdown_signal, previous_handler)
            except (ValueError, OSError):
                pass
        if needs_stop:
            try:
                source.stop()
            except Exception as exc:
                log_event(logger, "audio_shutdown_failed", error=str(exc))
        try:
            camera.emergency_stop()
        except Exception as exc:
            log_event(logger, "camera_stop_on_shutdown_failed", error=str(exc))
        try:
            camera.disconnect_all()
        except Exception as exc:
            log_event(logger, "camera_disconnect_on_shutdown_failed", error=str(exc))
        try:
            if dashboard_state is not None:
                dashboard_state.add_event("shutdown", "SPEAKERPTZ shutting down")
            if dashboard_server is not None:
                dashboard_server.stop()
        except Exception as exc:
            log_event(logger, "dashboard_shutdown_failed", error=str(exc))
        try:
            runtime_state.mark_clean_shutdown()
        except OSError as exc:
            log_event(logger, "clean_shutdown_state_failed", error=str(exc))
        finally:
            instance_lock.release()
        log_event(logger, "shutdown", clean=True)
        print("\nStopped.")


def _classified_exit_code(message: str) -> int:
    upper = message.upper()
    if upper.startswith("CONFIG ERROR"):
        return 2
    if upper.startswith(("AUDIO DEVICE ERROR", "CHANNEL IDENTIFIER")):
        return 3
    if upper.startswith(("CAMERA ", "CAMERA PROBE", "CAMERA TEST")):
        return 4
    if upper.startswith("DASHBOARD STARTUP ERROR"):
        return 5
    if upper.startswith("INSTANCE ERROR"):
        return 6
    return 1


def cli() -> int:
    # Redirected Windows PowerShell output commonly uses a legacy code page.
    # Never let a device name or operator-facing message crash the controller.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except (OSError, ValueError):
                pass
    try:
        main()
        return 0
    except SystemExit as exc:
        if isinstance(exc.code, int):
            return exc.code
        message = str(exc.code or "")
        if message:
            print(message, file=sys.stderr)
        return _classified_exit_code(message)


if __name__ == "__main__":
    raise SystemExit(cli())
