from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioDeviceMatch:
    index: int
    name: str
    max_input_channels: int
    hostapi: int


def list_input_devices(sd_module=None) -> list[AudioDeviceMatch]:
    if sd_module is None:
        import sounddevice as sd_module
    devices = sd_module.query_devices()
    out: list[AudioDeviceMatch] = []
    for idx, d in enumerate(devices):
        max_in = int(d.get("max_input_channels", 0))
        if max_in > 0:
            out.append(
                AudioDeviceMatch(
                    index=idx,
                    name=str(d.get("name", f"Device {idx}")),
                    max_input_channels=max_in,
                    hostapi=int(d.get("hostapi", -1)),
                )
            )
    return out


def resolve_input_device(device_index=None, device_name: str | None = None, channels: int = 1, sd_module=None) -> AudioDeviceMatch:
    devices = list_input_devices(sd_module=sd_module)

    if device_index is not None:
        matches = [d for d in devices if d.index == int(device_index)]
        if not matches:
            raise ValueError(f"Audio input device index {device_index} was not found.")
        match = matches[0]
    elif device_name:
        needle = device_name.strip().lower()
        matches = [d for d in devices if needle in d.name.lower()]
        if not matches:
            names = ", ".join(f"{d.index}:{d.name}" for d in devices)
            raise ValueError(f"No input device matched '{device_name}'. Available inputs: {names}")
        # Prefer a match that can actually satisfy the requested channel count.
        capable = [d for d in matches if d.max_input_channels >= int(channels)]
        match = capable[0] if capable else matches[0]
    else:
        raise ValueError("No audio input device configured. Set runtime.device_name or use --device/--device-name.")

    if match.max_input_channels < int(channels):
        raise ValueError(
            f"Audio device '{match.name}' exposes {match.max_input_channels} input channel(s), "
            f"but SPEAKERPTZ is configured for {channels}."
        )
    return match
