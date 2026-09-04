from __future__ import annotations

import platform
import sys
from pathlib import Path

from speakerptz.audio.channelmap import normalize_channel_map, required_physical_channels
from speakerptz.audio.devices import list_input_devices, resolve_input_device
from speakerptz.core.config import load_config, ConfigError
from speakerptz.cameras.base import CameraConnectionError
from speakerptz.cameras.manager import CameraManager
from speakerptz.cameras.models import CameraState


def run_doctor(config_path: str) -> int:
    failures = 0
    print("SPEAKERPTZ STARTUP DOCTOR")
    print("=" * 88)

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
    audio = cfg["audio"]
    logical_channels = int(audio["channels"])
    channel_map = normalize_channel_map(audio.get("channel_map"), logical_channels)
    physical_needed = required_physical_channels(channel_map)
    device_index = runtime.get("device_index")
    device_name = runtime.get("device_name")
    hostapi_name = runtime.get("hostapi_name")

    print(f"[PASS] Channel map: {logical_channels} logical mic(s) -> physical inputs {channel_map}")

    simulation_mode = runtime.get("mode", "real") == "simulate"
    print("\nWindows audio inputs visible to Python:")
    try:
        devices = list_input_devices()
        for d in devices:
            api = f" | {d.hostapi_name}" if d.hostapi_name else ""
            print(f"  {d.index:>3} | {d.max_input_channels:>2} ch | {d.name}{api}")
        if not devices:
            print("  (none)")
            failures += 1
    except Exception as exc:
        level = "WARN" if simulation_mode else "FAIL"
        print(f"[{level}] Could not enumerate audio devices: {exc}")
        failures += 0 if simulation_mode else 1
        devices = []

    if simulation_mode:
        print("\n[PASS] Runtime mode: simulation")
    else:
        try:
            match = resolve_input_device(
                device_index=device_index,
                device_name=device_name,
                channels=physical_needed,
                hostapi_name=hostapi_name,
            )
            import sounddevice as sd
            sample_rate = int(audio.get("sample_rate", 48000))
            sd.check_input_settings(device=match.index, channels=physical_needed, samplerate=sample_rate)
            api = f" | {match.hostapi_name}" if match.hostapi_name else ""
            print(
                f"\n[PASS] Audio device: {match.index} | {match.name}{api} | "
                f"opens {physical_needed} physical ch @ {sample_rate} Hz"
            )
            expected = str(runtime.get("device_name") or "").strip().lower()
            if "dante" in expected and "dante" not in match.name.lower():
                print("[WARN] Config expects a Dante-named device but the resolved Windows device name does not contain 'Dante'.")
        except Exception as exc:
            print(f"\n[FAIL] Audio device: {exc}")
            failures += 1

    logs = Path(str(runtime.get("log_dir", "logs")))
    try:
        logs.mkdir(exist_ok=True)
        test = logs / ".write_test"
        test.write_text("ok", encoding="utf-8")
        test.unlink(missing_ok=True)
        print("[PASS] Logs directory is writable")
    except Exception as exc:
        print(f"[FAIL] Logs directory: {exc}")
        failures += 1

    real_control = bool(cfg.get("real_control_enabled", False))
    if real_control:
        print("\n[WARN] CAMERA SAFETY: REAL PTZ CONTROL ENABLED")
    else:
        print("\n[PASS] Camera safety: SIMULATION / DRY RUN; real PTZ transmission disabled")

    try:
        cameras = CameraManager.from_config(cfg)
        camera_health = cameras.connect_all()
        for camera_id, camera_cfg in cameras.configs.items():
            health = camera_health[camera_id]
            configured = camera_cfg.driver.upper()
            effective = configured if real_control else "SIMULATOR"
            prefix = "PASS" if health.ok or health.state == CameraState.DISABLED else "FAIL"
            print(
                f"[{prefix}] Camera {camera_id}: {camera_cfg.name} | configured={configured} | "
                f"effective={effective} | {health.state.value.upper()}"
            )
            if camera_cfg.enabled and not health.ok:
                failures += 1
                if health.last_error:
                    print(f"       {health.last_error}")
        cameras.disconnect_all()
    except CameraConnectionError as exc:
        print(f"[FAIL] Camera configuration/credentials: {exc}")
        failures += 1

    print("=" * 88)
    print("DOCTOR RESULT:", "PASS" if failures == 0 else f"FAIL ({failures} issue(s))")
    return 0 if failures == 0 else 1
