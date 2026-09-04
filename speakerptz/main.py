from __future__ import annotations

import argparse
import os
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


VERSION = "0.6"


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


def render(levels, detector, routes, mode, auto_enabled, camera, device_label="", channel_map=None, audio_warning=""):
    os.system("cls" if os.name == "nt" else "clear")
    snap = detector.snapshot()
    print(f"SPEAKERPTZ v{VERSION}")
    print("=" * 104)

    if snap.calibrating:
        print(f"CALIBRATING ROOM NOISE: {snap.calibration_remaining:0.1f}s remaining — stay quiet")
        print("-" * 104)

    channel_map = channel_map or list(range(1, len(levels) + 1))
    for idx, db in enumerate(levels, start=1):
        route = routes.get(idx)
        name = route.name if route else f"Mic {idx}"
        physical = channel_map[idx - 1] if idx - 1 < len(channel_map) else idx
        bars = max(0, min(24, int((db + 70) / 2)))
        floor = snap.noise_floors[idx - 1] if idx - 1 < len(snap.noise_floors) else None
        snr = snap.snr_db[idx - 1] if idx - 1 < len(snap.snr_db) else None
        marker = "  < ACTIVE" if detector.active == idx else ""
        floor_text = f"floor {floor:6.1f}" if floor is not None else "floor   --.-"
        snr_text = f"+{snr:4.1f}" if snr is not None and snr >= 0 else (f"{snr:5.1f}" if snr is not None else "  --.-")
        print(
            f"MIC {idx:02d} <- IN {physical:02d} | {name[:18]:18} {db:6.1f} dB | "
            f"{floor_text} | SNR {snr_text} | {'█' * bars}{marker}"
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
    print(f"AUTO DIRECTOR: {'ON' if auto_enabled else 'OFF / MANUAL'}")
    print(f"MODE: {mode}")
    if device_label:
        print(f"AUDIO DEVICE: {device_label}")
    if audio_warning:
        print(f"AUDIO FAIL-SAFE: {audio_warning}")
    print(f"CAMERA CONTROL: {camera.mode_banner}")
    if camera.emergency_stopped:
        print("CAMERA SAFETY: EMERGENCY STOP LATCHED — PRESS R TO RESET; AUTO STAYS OFF")
    for camera_id, health in camera.health_all().items():
        detail = f" | {health.message}" if health.message else ""
        print(f"CAM {camera_id}: {health.state.value.upper()}{detail}")
    print(f"LAST CAMERA REQUEST: {camera.last_action}")
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
    print(f"RESULT: {health.state.value.upper()} — {health.message or health.last_error or ''}")
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
    args = parser.parse_args()

    if args.list_devices:
        from .audio.devices import list_input_devices
        for d in list_input_devices():
            api = f" | {d.hostapi_name}" if d.hostapi_name else ""
            print(f"{d.index:>3} | {d.max_input_channels:>2} in | {d.name}{api}")
        return

    if args.doctor:
        from .runtime.doctor import run_doctor
        raise SystemExit(run_doctor(args.config))

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

    logger = setup_logging(str(runtime_cfg.get("log_dir", "logs")))
    try:
        camera = CameraManager.from_config(cfg, logger=logger)
    except CameraConnectionError as exc:
        raise SystemExit(f"CAMERA CONFIGURATION ERROR: {exc}")

    if args.camera_probe is not None:
        raise SystemExit(run_camera_probe(cfg, camera, args.camera_probe))
    if args.camera_test is not None:
        raise SystemExit(run_camera_test(cfg, camera, args.camera_test))

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
        run_identifier(match.index, count, sample_rate, f"{match.index} | {match.name}")
        return

    detector = build_detector(audio_cfg)
    wide = cfg["wide_shot"]
    controls = ConsoleControls()
    device_label = ""
    audio_warning = ""
    stale_logged = False

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

    running = True
    try:
        while running:
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

            levels = source.read_levels()
            audio_ok = True
            audio_warning = ""
            if needs_stop:
                health = source.health(float(runtime_cfg.get("audio_stale_seconds", 1.5)))
                if not health.ok:
                    audio_ok = False
                    audio_warning = f"PAUSED — no audio callback for {health.stale_seconds:.1f}s"
                    if auto_enabled:
                        auto_enabled = False
                    if not stale_logged:
                        camera.emergency_stop()
                        log_event(logger, "audio_stale", seconds=round(health.stale_seconds, 3), status=health.callback_status)
                        stale_logged = True
                else:
                    if stale_logged:
                        log_event(logger, "audio_recovered")
                    stale_logged = False
                    if health.callback_status:
                        audio_warning = health.callback_status

            event = detector.update(levels) if audio_ok else None
            if auto_enabled and event:
                kind, channel = event
                if kind == "speaker" and channel in routes:
                    r = routes[channel]
                    result = camera.goto_preset(r.camera, r.preset, r.name)
                    log_event(logger, "speaker_change", mic_channel=channel, name=r.name, confidence=round(detector.confidence, 4), camera=r.camera, preset=r.preset, accepted=result.accepted, reason=result.reason)
                elif kind == "silence":
                    result = camera.goto_preset(int(wide["camera"]), int(wide["preset"]), "Wide shot")
                    log_event(logger, "silence_wide", camera=int(wide["camera"]), preset=int(wide["preset"]), accepted=result.accepted, reason=result.reason)

            render(levels, detector, routes, mode, auto_enabled, camera, device_label, channel_map, audio_warning)
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        if needs_stop:
            source.stop()
        camera.emergency_stop()
        camera.disconnect_all()
        log_event(logger, "shutdown")
        print("\nStopped.")


if __name__ == "__main__":
    main()
