from __future__ import annotations

from pathlib import Path
import yaml
from .models import PersonRoute


class ConfigError(ValueError):
    pass


def _require_int(mapping, key, minimum=0):
    try:
        value = int(mapping[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"Missing or invalid integer: {key}") from exc
    if value < minimum:
        raise ConfigError(f"{key} must be >= {minimum}")
    return value


def validate_config(data: dict) -> None:
    if not isinstance(data, dict):
        raise ConfigError("Configuration must be a YAML mapping.")
    if "audio" not in data or not isinstance(data["audio"], dict):
        raise ConfigError("Missing audio section.")
    if "people" not in data or not isinstance(data["people"], list) or not data["people"]:
        raise ConfigError("people must contain at least one route.")
    if "wide_shot" not in data or not isinstance(data["wide_shot"], dict):
        raise ConfigError("Missing wide_shot section.")

    channels = _require_int(data["audio"], "channels", 1)
    seen = set()
    for p in data["people"]:
        if not isinstance(p, dict):
            raise ConfigError("Every people entry must be a mapping.")
        mic = _require_int(p, "mic_channel", 1)
        _require_int(p, "camera", 1)
        _require_int(p, "preset", 0)
        if not str(p.get("name", "")).strip():
            raise ConfigError(f"Mic channel {mic} is missing a name.")
        if mic > channels:
            raise ConfigError(f"Mic channel {mic} exceeds configured audio.channels={channels}.")
        if mic in seen:
            raise ConfigError(f"Duplicate mic_channel: {mic}")
        seen.add(mic)

    _require_int(data["wide_shot"], "camera", 1)
    _require_int(data["wide_shot"], "preset", 0)


def load_config(path: str):
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(
            f"Config file not found: {config_path}. Copy config/local.example.yaml to config/local.yaml "
            "for the school computer, or pass --config config/room.yaml for development."
        )
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    validate_config(data)
    routes = {
        int(p["mic_channel"]): PersonRoute(
            mic_channel=int(p["mic_channel"]),
            name=str(p["name"]),
            camera=int(p["camera"]),
            preset=int(p["preset"]),
        )
        for p in data["people"]
    }
    return data, routes
