from __future__ import annotations

from pathlib import Path
import ipaddress
import re
import yaml
from .models import PersonRoute
from speakerptz.audio.channelmap import normalize_channel_map


class ConfigError(ValueError):
    pass


SUPPORTED_CAMERA_DRIVERS = {"simulator", "visca", "onvif"}
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _require_int(mapping, key, minimum=0):
    try:
        value = int(mapping[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"Missing or invalid integer: {key}") from exc
    if value < minimum:
        raise ConfigError(f"{key} must be >= {minimum}")
    return value


def _require_number(mapping, key, default, minimum=0.0):
    try:
        value = float(mapping.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"Missing or invalid number: {key}") from exc
    if value < minimum:
        raise ConfigError(f"{key} must be >= {minimum}")
    return value


def _number_between(mapping, key, default, minimum, maximum):
    value = _require_number(mapping, key, default, minimum)
    if value > maximum:
        raise ConfigError(f"{key} must be between {minimum} and {maximum}")
    return value


def _validate_audio_detection(audio: dict, channels: int) -> None:
    for key in ("vad_enabled", "adaptive_noise_enabled"):
        if key in audio and not isinstance(audio[key], bool):
            raise ConfigError(f"audio.{key} must be true or false.")

    for key, default in (
        ("confidence_min", 0.55),
        ("vad_threshold", 0.55),
        ("vad_weight", 0.45),
        ("confidence_smoothing", 0.35),
        ("adaptive_noise_alpha", 0.02),
    ):
        _number_between(audio, key, default, 0.0, 1.0)

    transient = _require_int(audio, "transient_rejection_ms", 0) if "transient_rejection_ms" in audio else 180
    if transient > 5000:
        raise ConfigError("audio.transient_rejection_ms must not exceed 5000.")
    _require_number(audio, "overlap_margin_db", 2.0)
    _require_number(audio, "bleed_rejection_db", 6.0)

    try:
        floor_min = float(audio.get("noise_floor_min_db", -85.0))
        floor_max = float(audio.get("noise_floor_max_db", -35.0))
    except (TypeError, ValueError) as exc:
        raise ConfigError("audio noise-floor bounds must be numbers.") from exc
    if not -120.0 <= floor_min < floor_max <= 0.0:
        raise ConfigError("audio noise-floor bounds must satisfy -120 <= min < max <= 0 dB.")

    offsets = audio.get("level_offsets_db", [])
    if not isinstance(offsets, list):
        raise ConfigError("audio.level_offsets_db must be a list.")
    if offsets and len(offsets) != channels:
        raise ConfigError(f"audio.level_offsets_db must contain exactly {channels} values.")
    try:
        [float(value) for value in offsets]
    except (TypeError, ValueError) as exc:
        raise ConfigError("audio.level_offsets_db values must be numbers.") from exc

    disabled = audio.get("disabled_channels", [])
    if not isinstance(disabled, list):
        raise ConfigError("audio.disabled_channels must be a list.")
    try:
        disabled_values = [int(value) for value in disabled]
    except (TypeError, ValueError) as exc:
        raise ConfigError("audio.disabled_channels values must be integers.") from exc
    if len(set(disabled_values)) != len(disabled_values):
        raise ConfigError("audio.disabled_channels contains duplicates.")
    if any(value < 1 or value > channels for value in disabled_values):
        raise ConfigError(f"audio.disabled_channels values must be between 1 and {channels}.")

    pairs = audio.get("bleed_pairs", [])
    if not isinstance(pairs, list):
        raise ConfigError("audio.bleed_pairs must be a list of two-channel pairs.")
    normalized_pairs = set()
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ConfigError("Every audio.bleed_pairs entry must contain exactly two channels.")
        try:
            first, second = int(pair[0]), int(pair[1])
        except (TypeError, ValueError) as exc:
            raise ConfigError("audio.bleed_pairs channel values must be integers.") from exc
        if first == second or not (1 <= first <= channels and 1 <= second <= channels):
            raise ConfigError(f"audio.bleed_pairs channels must be distinct and between 1 and {channels}.")
        normalized = tuple(sorted((first, second)))
        if normalized in normalized_pairs:
            raise ConfigError(f"Duplicate audio.bleed_pairs relationship: {normalized}")
        normalized_pairs.add(normalized)


def _validate_dashboard(data: dict) -> None:
    dashboard = data.get("dashboard", {})
    if not isinstance(dashboard, dict):
        raise ConfigError("dashboard must be a mapping.")
    for key in ("enabled", "allow_remote"):
        if key in dashboard and not isinstance(dashboard[key], bool):
            raise ConfigError(f"dashboard.{key} must be true or false.")

    host = str(dashboard.get("host", "127.0.0.1")).strip()
    if not host:
        raise ConfigError("dashboard.host must not be empty.")
    loopback = host.lower() == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    if not loopback and dashboard.get("allow_remote", False) is not True:
        raise ConfigError(
            "dashboard.host is not loopback; set dashboard.allow_remote: true only after an explicit network-access decision."
        )

    port = _require_int(dashboard, "port", 1) if "port" in dashboard else 8765
    if port > 65535:
        raise ConfigError("dashboard.port must be between 1 and 65535.")


def _validate_cameras(data: dict) -> dict[int, dict]:
    if "real_control_enabled" in data and not isinstance(data["real_control_enabled"], bool):
        raise ConfigError("real_control_enabled must be true or false.")

    control = data.get("camera_control", {})
    if not isinstance(control, dict):
        raise ConfigError("camera_control must be a mapping.")
    _require_number(control, "command_interval_seconds", 0.10)
    _require_number(control, "movement_cooldown_seconds", 0.75)
    _require_number(control, "retry_backoff_seconds", 0.10)
    retries = _require_int(control, "retry_count", 0) if "retry_count" in control else 1
    if retries > 3:
        raise ConfigError("camera_control.retry_count must be between 0 and 3.")

    cameras = data.get("cameras")
    if cameras is None:
        return {}
    if not isinstance(cameras, list) or not cameras:
        raise ConfigError("cameras must contain at least one camera entry.")

    by_id = {}
    for camera in cameras:
        if not isinstance(camera, dict):
            raise ConfigError("Every cameras entry must be a mapping.")
        camera_id = _require_int(camera, "id", 1)
        if camera_id in by_id:
            raise ConfigError(f"Duplicate camera id: {camera_id}")
        if "password" in camera:
            raise ConfigError(
                f"Camera {camera_id} contains plaintext password; use password_env and an environment variable."
            )
        if "enabled" in camera and not isinstance(camera["enabled"], bool):
            raise ConfigError(f"Camera {camera_id} enabled must be true or false.")
        driver = str(camera.get("driver", "simulator")).strip().lower()
        if driver not in SUPPORTED_CAMERA_DRIVERS:
            raise ConfigError(
                f"Camera {camera_id} has unsupported driver {driver!r}; use simulator, visca, or onvif."
            )
        if not isinstance(camera.get("name"), str) or not camera["name"].strip():
            raise ConfigError(f"Camera {camera_id} is missing a name.")
        if driver in {"visca", "onvif"} and (
            not isinstance(camera.get("host"), str) or not camera["host"].strip()
        ):
            raise ConfigError(f"Camera {camera_id} driver {driver} requires host.")
        if camera.get("port") is not None:
            port = _require_int(camera, "port", 1)
            if port > 65535:
                raise ConfigError(f"Camera {camera_id} port must be between 1 and 65535.")
        timeout = _require_number(camera, "timeout_seconds", 1.0, 0.05)
        if timeout > 30:
            raise ConfigError(f"Camera {camera_id} timeout_seconds must not exceed 30.")
        password_env = str(camera.get("password_env") or "")
        if password_env and not ENV_NAME.match(password_env):
            raise ConfigError(f"Camera {camera_id} password_env is not a valid environment variable name.")
        if driver == "onvif":
            if not isinstance(camera.get("username"), str) or not camera["username"].strip():
                raise ConfigError(f"Camera {camera_id} ONVIF driver requires username.")
            if not password_env:
                raise ConfigError(f"Camera {camera_id} ONVIF driver requires password_env, never a plaintext password.")
        by_id[camera_id] = camera
    return by_id


def validate_config(data: dict) -> None:
    if not isinstance(data, dict):
        raise ConfigError("Configuration must be a YAML mapping.")
    if "audio" not in data or not isinstance(data["audio"], dict):
        raise ConfigError("Missing audio section.")
    if "people" not in data or not isinstance(data["people"], list) or not data["people"]:
        raise ConfigError("people must contain at least one route.")
    if "wide_shot" not in data or not isinstance(data["wide_shot"], dict):
        raise ConfigError("Missing wide_shot section.")

    _validate_dashboard(data)
    cameras = _validate_cameras(data)

    channels = _require_int(data["audio"], "channels", 1)
    try:
        normalize_channel_map(data["audio"].get("channel_map"), channels)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    _validate_audio_detection(data["audio"], channels)

    seen = set()
    for p in data["people"]:
        if not isinstance(p, dict):
            raise ConfigError("Every people entry must be a mapping.")
        mic = _require_int(p, "mic_channel", 1)
        camera_id = _require_int(p, "camera", 1)
        preset = _require_int(p, "preset", 0)
        if not str(p.get("name", "")).strip():
            raise ConfigError(f"Mic channel {mic} is missing a name.")
        if mic > channels:
            raise ConfigError(f"Mic channel {mic} exceeds configured audio.channels={channels}.")
        if mic in seen:
            raise ConfigError(f"Duplicate mic_channel: {mic}")
        if cameras:
            if camera_id not in cameras:
                raise ConfigError(f"Mic channel {mic} references unknown camera {camera_id}.")
            if cameras[camera_id].get("enabled", True) is not True:
                raise ConfigError(f"Mic channel {mic} references disabled camera {camera_id}.")
            if str(cameras[camera_id].get("driver", "simulator")).lower() == "visca" and not 1 <= preset <= 64:
                raise ConfigError(f"Mic channel {mic} VISCA preset must be between 1 and 64.")
        seen.add(mic)

    wide_camera = _require_int(data["wide_shot"], "camera", 1)
    wide_preset = _require_int(data["wide_shot"], "preset", 0)
    if cameras:
        if wide_camera not in cameras:
            raise ConfigError(f"wide_shot references unknown camera {wide_camera}.")
        if cameras[wide_camera].get("enabled", True) is not True:
            raise ConfigError(f"wide_shot references disabled camera {wide_camera}.")
        if str(cameras[wide_camera].get("driver", "simulator")).lower() == "visca" and not 1 <= wide_preset <= 64:
            raise ConfigError("wide_shot VISCA preset must be between 1 and 64.")


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
