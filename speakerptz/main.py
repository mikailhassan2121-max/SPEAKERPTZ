from __future__ import annotations

import argparse
import os
import time

from .audio.simulator import SimulatedAudioSource
from .cameras.simulator import SimulatorCamera
from .core.config import load_config
from .core.detector import ActiveSpeakerDetector


class ConsoleControls:
    """Small Windows-console manual override layer; safely no-ops elsewhere."""

    def poll(self):
        if os.name != "nt":
            return None
        try:
            import msvcrt
            if not msvcrt.kbhit():
                return None
            key = msvcrt.getwch().lower()
            return key
        except Exception:
            return None


def render(levels, detector, routes, mode, auto_enabled, camera):
    os.system("cls" if os.name == "nt" else "clear")
    snap = detector.snapshot()
    print("SPEAKERPTZ v0.3")
    print("=" * 92)

    if snap.calibrating:
        print(f"CALIBRATING ROOM NOISE: {snap.calibration_remaining:0.1f}s remaining — stay quiet")
        print("-" * 92)

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
    print("CAMERA CONTROL: SIMULATION ONLY")
    print(f"LAST CAMERA REQUEST: {camera.last_action}")
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
    parser.add_argument("--channels", type=int, help="Override input channel count")
    parser.add_argument("--list-devices", action="store_true", help="Print audio devices and exit")
    args = parser.parse_args()

    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return

    cfg, routes = load_config(args.config)
    audio_cfg = cfg["audio"]
    channels = int(args.channels or audio_cfg["channels"])
    sample_rate = int(audio_cfg.get("sample_rate", 48000))

    camera = SimulatorCamera()
    detector = build_detector(audio_cfg)
    wide = cfg["wide_shot"]
    controls = ConsoleControls()
    auto_enabled = True

    if args.simulate:
        source = SimulatedAudioSource(channels)
        mode = "SIMULATION"
        needs_stop = False
    else:
        import sounddevice as sd
        from .audio.realtime import RealAudioSource
        if args.device is None:
            raise SystemExit("Real-audio mode requires --device N. Use --list-devices to see device numbers.")
        sd.check_input_settings(device=args.device, channels=channels, samplerate=sample_rate)
        source = RealAudioSource(args.device, channels, sample_rate)
        source.start()
        mode = f"REAL AUDIO | DEVICE {args.device} | {channels} CH @ {sample_rate} Hz"
        needs_stop = True

    running = True
    try:
        while running:
            key = controls.poll()
            if key == "q":
                running = False
                continue
            if key == "a":
                auto_enabled = not auto_enabled
            elif key == "w":
                camera.goto_preset(int(wide["camera"]), int(wide["preset"]), "Wide shot (manual)")
            elif key and key.isdigit() and key != "0":
                channel = int(key)
                if channel in routes:
                    auto_enabled = False
                    r = routes[channel]
                    camera.goto_preset(r.camera, r.preset, f"{r.name} (manual)")

            levels = source.read_levels()
            event = detector.update(levels)
            if auto_enabled and event:
                kind, channel = event
                if kind == "speaker" and channel in routes:
                    r = routes[channel]
                    camera.goto_preset(r.camera, r.preset, r.name)
                elif kind == "silence":
                    camera.goto_preset(int(wide["camera"]), int(wide["preset"]), "Wide shot")

            render(levels, detector, routes, mode, auto_enabled, camera)
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        if needs_stop:
            source.stop()
        print("\nStopped.")


if __name__ == "__main__":
    main()
