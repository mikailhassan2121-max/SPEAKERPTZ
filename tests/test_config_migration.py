import pytest

from speakerptz.core.config import ConfigError, migrate_config, validate_config


def legacy_config():
    return {
        "runtime": {"mode": "simulate"},
        "audio": {"channels": 1, "channel_map": [1]},
        "people": [{"mic_channel": 1, "name": "A", "camera": 1, "preset": 1}],
        "wide_shot": {"camera": 1, "preset": 20},
    }


def test_legacy_config_is_non_destructively_interpreted_as_schema_one():
    original = legacy_config()
    migrated, notes = migrate_config(original)
    assert "config_version" not in original
    assert migrated["config_version"] == 1
    assert notes
    validate_config(migrated)


@pytest.mark.parametrize("version", [0, 2, "1", True])
def test_unknown_or_malformed_config_schema_is_rejected(version):
    config = legacy_config()
    config["config_version"] = version
    with pytest.raises(ConfigError, match="config_version"):
        validate_config(config)


def test_reconnect_bounds_are_validated():
    config = legacy_config()
    config["camera_control"] = {"reconnect_attempt_limit": 11}
    with pytest.raises(ConfigError, match="reconnect_attempt_limit"):
        validate_config(config)
    config = legacy_config()
    config["runtime"]["audio_reconnect_attempts"] = 11
    with pytest.raises(ConfigError, match="audio_reconnect_attempts"):
        validate_config(config)
