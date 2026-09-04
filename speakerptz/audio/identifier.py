from __future__ import annotations

import os
import time

from .realtime import RealAudioSource


def run_identifier(device_index: int, channels: int, sample_rate: int, device_label: str = "") -> None:
    """Live physical-channel meter used to discover Dante/DVS channel numbering.

    This deliberately bypasses the speaker detector and seat mapping. The operator
    speaks into one physical microphone at a time and notes which DVS channel peaks.
    """
    source = RealAudioSource(
        device=device_index,
        channels=channels,
        sample_rate=sample_rate,
        channel_map=list(range(1, channels + 1)),
    )
    source.start()
    try:
        while True:
            if os.name == "nt":
                try:
                    import msvcrt
                    if msvcrt.kbhit() and msvcrt.getwch().lower() == "q":
                        break
                except Exception:
                    pass

            levels = source.read_levels()
            best = max(range(len(levels)), key=lambda i: levels[i]) if levels else None
            os.system("cls" if os.name == "nt" else "clear")
            print("SPEAKERPTZ DANTE / MULTICHANNEL IDENTIFIER")
            print("=" * 76)
            if device_label:
                print(f"DEVICE: {device_label}")
            print(f"INPUTS OPEN: 1-{channels} @ {sample_rate} Hz")
            print("Speak into ONE board microphone at a time. Note the physical input that peaks.")
            print()
            for idx, db in enumerate(levels, start=1):
                bars = max(0, min(32, int((db + 80) / 2)))
                marker = "  < PEAK" if best == idx - 1 and db > -55 else ""
                print(f"PHYS {idx:02d}  {db:6.1f} dB | {'#' * bars}{marker}")
            health = source.health()
            if not health.ok:
                print(f"\nAUDIO WARNING: no callback for {health.stale_seconds:.1f}s")
            elif health.callback_status:
                print(f"\nAUDIO STATUS: {health.callback_status}")
            print("\nQ = quit")
            time.sleep(0.10)
    finally:
        source.stop()
