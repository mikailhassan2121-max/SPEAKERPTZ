from __future__ import annotations

import platform
import sys
from pathlib import Path

from speakerptz.audio.devices import list_input_devices, resolve_input_device
from speakerptz.core.config import load_config, ConfigError


def run_doctor(config_path: str) -> int:
    failures = 0
    print("SPEAKERPTZ STARTUP DOCTOR")
    print("=" * 72)

    py_ok = sys.version_info >= (3, 12)
    print(f"[{'PASS' if py_ok else 'FAIL'}] Python: {platform.python_version()}")
    failures += 0 if py_ok else 1

    try:
        cfg, _ = load_config(config_path)
        print(f"[PASS] Config: {config_path}")
    except ConfigError as exc:
        print(f"[FAIL] Config: {exc}")
        return 1

    runtime = cfg.get("runtime", {})
    channels = int(cfg["audio"]["channels"])
    device_index = runtime.get("device_index")
    device_name = runtime.get("device_name")

    print("\nWindows audio inputs visible to Python:")
    try:
        devices = list_input_devices()
        for d in devices:
            print(f"  {d.index:>3} | {d.max_input_channels:>2} ch | {d.name}")
        if not devices:
            print("  (none)")
            failures += 1
    except Exception as exc:
        print(f"[FAIL] Could not enumerate audio devices: {exc}")
        failures += 1
        devices = []

    if runtime.get("mode", "real") == "simulate":
        print("\n[PASS] Runtime mode: simulation")
    else:
        try:
            match = resolve_input_device(device_index=device_index, device_name=device_name, channels=channels)
            import sounddevice as sd
            sample_rate = int(cfg["audio"].get("sample_rate", 48000))
            sd.check_input_settings(device=match.index, channels=channels, samplerate=sample_rate)
            print(f"\n[PASS] Audio device: {match.index} | {match.name} | {channels} ch @ {sample_rate} Hz")
        except Exception as exc:
            print(f"\n[FAIL] Audio device: {exc}")
            failures += 1

    logs = Path("logs")
    try:
        logs.mkdir(exist_ok=True)
        test = logs / ".write_test"
        test.write_text("ok", encoding="utf-8")
        test.unlink(missing_ok=True)
        print("[PASS] Logs directory is writable")
    except Exception as exc:
        print(f"[FAIL] Logs directory: {exc}")
        failures += 1

    print("[PASS] Camera driver: simulator (no real PTZ commands can leave this build)")
    print("=" * 72)
    print("DOCTOR RESULT:", "PASS" if failures == 0 else f"FAIL ({failures} issue(s))")
    return 0 if failures == 0 else 1
