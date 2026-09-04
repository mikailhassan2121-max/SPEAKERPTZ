from __future__ import annotations

import argparse
import os
import time

from .audio.simulator import SimulatedAudioSource
from .audio.devices import resolve_input_device
from .cameras.simulator import SimulatorCamera
from .core.config import load_config, ConfigError
from .core.detector import ActiveSpeakerDetector
from .runtime.logging import setup_logging, event as log_event


VERSION = "0.4"


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


def render(levels, detector, routes, mode, auto_enabled, camera, device_label=""):
    os.system("cls" if os.name == "nt" else "clear")
    snap = detector.snapshot()
    print(f"SPEAKERPTZ v{VERSION}")
    print("=" * 96)

    if snap.calibrating:
        print(f"CALIBRATING ROOM NOISE: {snap.calibration_remaining:0.1f}s remaining — stay quiet")
        print("-" * 96)

    for idx, db in enumerate(levels, start=1):
        route = routes.get(idx)
        name = route.name if route else f"Mic {idx}"
        bars = max(0, min(24, int((db + 70) / 2)))
        floor = snap.noise_floors[idx - 1] if idx - 1 < len(snap.noise_floors) else None
        snr = snap.snr_db[idx - 1] if idx - 1 < len(snap.snr_db) else None
        marker = "  < ACTIVE" if detector.active == idx else ""
        floor_text = f"floor {floor:6.1f}" if floor is not None else "floor   --.-"
        snr_text = f"+{snr:4.1f}" if snr is not None and snr >= 0 else (f"{snr:5.1f}" if snr is not None else "  --.-")
        print(f"CH {idx:02d}  {name[:20]:20} {db:6.1f} dB | {floor_text} | SNR {snr_text} | {'█' * bars}{marker}")

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
    print("CAMERA CONTROL: SIMULATION ONLY (SAFE DRY RUN)")
    print(f"LAST CAMERA REQUEST: {camera.last_action}")
    print("LOGGING: ON -> logs\\speakerptz-YYYYMMDD.log")
    print()
    print("HOTKEYS: A = auto on/off | W = wide | 1-9 = manual seat preset (turns auto off) | Q = quit")


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
    parser.add_argument("--channels", type=int, help="Override input channel count")
    parser.add_argument("--list-devices", action="store_true", help="Print audio devices and exit")
    parser.add_argument("--doctor", action="store_true", help="Run startup self-test and exit")
    args = parser.parse_args()

    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
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

    logger = setup_logging(str(runtime_cfg.get("log_dir", "logs")))
    camera = SimulatorCamera()
    detector = build_detector(audio_cfg)
    wide = cfg["wide_shot"]
    controls = ConsoleControls()
    auto_enabled = bool(runtime_cfg.get("auto_start", True))

    requested_sim = args.simulate or runtime_cfg.get("mode", "real") == "simulate"
    device_label = ""

    if requested_sim:
        source = SimulatedAudioSource(channels)
        mode = "SIMULATION"
        needs_stop = False
        log_event(logger, "startup", version=VERSION, mode=mode, channels=channels)
    else:
        import sounddevice as sd
        from .audio.realtime import RealAudioSource
        device_index = args.device if args.device is not None else runtime_cfg.get("device_index")
        device_name = args.device_name or runtime_cfg.get("device_name")
        try:
            match = resolve_input_device(device_index=device_index, device_name=device_name, channels=channels)
            sd.check_input_settings(device=match.index, channels=channels, samplerate=sample_rate)
        except Exception as exc:
            raise SystemExit(f"AUDIO DEVICE ERROR: {exc}\nRun: .venv\\Scripts\\python.exe -m speakerptz.main --list-devices")
        source = RealAudioSource(match.index, channels, sample_rate)
        source.start()
        mode = f"REAL AUDIO | {channels} CH @ {sample_rate} Hz"
        device_label = f"{match.index} | {match.name}"
        needs_stop = True
        log_event(logger, "startup", version=VERSION, mode=mode, device_index=match.index, device_name=match.name, channels=channels)

    running = True
    last_auto = auto_enabled
    try:
        while running:
            key = controls.poll()
            if key == "q":
                running = False
                continue
            if key == "a":
                auto_enabled = not auto_enabled
                log_event(logger, "auto_director", enabled=auto_enabled)
            elif key == "w":
                camera.goto_preset(int(wide["camera"]), int(wide["preset"]), "Wide shot (manual)")
                log_event(logger, "camera_request", source="manual", camera=int(wide["camera"]), preset=int(wide["preset"]), label="Wide shot")
            elif key and key.isdigit() and key != "0":
                channel = int(key)
                if channel in routes:
                    auto_enabled = False
                    r = routes[channel]
                    camera.goto_preset(r.camera, r.preset, f"{r.name} (manual)")
                    log_event(logger, "camera_request", source="manual", mic_channel=channel, camera=r.camera, preset=r.preset, label=r.name)

            levels = source.read_levels()
            event = detector.update(levels)
            if auto_enabled and event:
                kind, channel = event
                if kind == "speaker" and channel in routes:
                    r = routes[channel]
                    camera.goto_preset(r.camera, r.preset, r.name)
                    log_event(logger, "speaker_change", mic_channel=channel, name=r.name, confidence=round(detector.confidence, 4), camera=r.camera, preset=r.preset)
                elif kind == "silence":
                    camera.goto_preset(int(wide["camera"]), int(wide["preset"]), "Wide shot")
                    log_event(logger, "silence_wide", camera=int(wide["camera"]), preset=int(wide["preset"]))

            if auto_enabled != last_auto:
                last_auto = auto_enabled

            render(levels, detector, routes, mode, auto_enabled, camera, device_label)
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        if needs_stop:
            source.stop()
        log_event(logger, "shutdown")
        print("\nStopped.")


if __name__ == "__main__":
    main()
