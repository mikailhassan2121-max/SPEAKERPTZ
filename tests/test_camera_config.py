import copy

import pytest

from speakerptz.core.config import ConfigError, validate_config


def config_with_cameras():
    return {
        "runtime": {"mode": "simulate"},
        "real_control_enabled": False,
        "camera_control": {
            "command_interval_seconds": 0.1,
            "movement_cooldown_seconds": 0.75,
            "retry_count": 1,
            "retry_backoff_seconds": 0.1,
        },
        "cameras": [
            {
                "id": 1,
                "name": "Board",
                "driver": "simulator",
                "enabled": True,
                "host": None,
                "port": None,
                "username": None,
                "password_env": None,
            }
        ],
        "audio": {"channels": 1, "channel_map": [1]},
        "people": [{"mic_channel": 1, "name": "A", "camera": 1, "preset": 1}],
        "wide_shot": {"camera": 1, "preset": 20},
    }


def test_camera_config_valid():
    validate_config(config_with_cameras())


@pytest.mark.parametrize("driver", ["visca", "onvif"])
def test_real_driver_requires_host(driver):
    cfg = config_with_cameras()
    cfg["cameras"][0]["driver"] = driver
    if driver == "onvif":
        cfg["cameras"][0].update(username="operator", password_env="CAMERA_PASSWORD")
    with pytest.raises(ConfigError, match="requires host"):
        validate_config(cfg)


def test_plaintext_camera_password_is_rejected():
    cfg = config_with_cameras()
    cfg["cameras"][0]["password"] = "do-not-commit"
    with pytest.raises(ConfigError, match="plaintext password"):
        validate_config(cfg)


def test_onvif_requires_environment_variable_name():
    cfg = config_with_cameras()
    cfg["cameras"][0].update(driver="onvif", host="192.0.2.10", username="operator")
    with pytest.raises(ConfigError, match="requires password_env"):
        validate_config(cfg)


def test_duplicate_camera_id_is_rejected():
    cfg = config_with_cameras()
    cfg["cameras"].append(copy.deepcopy(cfg["cameras"][0]))
    with pytest.raises(ConfigError, match="Duplicate camera id"):
        validate_config(cfg)


def test_unknown_route_camera_is_rejected():
    cfg = config_with_cameras()
    cfg["people"][0]["camera"] = 9
    with pytest.raises(ConfigError, match="unknown camera 9"):
        validate_config(cfg)


def test_disabled_route_camera_is_rejected():
    cfg = config_with_cameras()
    cfg["cameras"][0]["enabled"] = False
    with pytest.raises(ConfigError, match="disabled camera"):
        validate_config(cfg)


def test_visca_route_preset_uses_documented_range():
    cfg = config_with_cameras()
    cfg["cameras"][0].update(driver="visca", host="192.0.2.10")
    cfg["people"][0]["preset"] = 65
    with pytest.raises(ConfigError, match="between 1 and 64"):
        validate_config(cfg)


def test_real_control_flag_must_be_boolean():
    cfg = config_with_cameras()
    cfg["real_control_enabled"] = "false"
    with pytest.raises(ConfigError, match="true or false"):
        validate_config(cfg)
