import copy

import pytest

from speakerptz.core.config import ConfigError, validate_config


def base_config():
    return {
        "runtime": {"mode": "simulate"},
        "audio": {
            "channels": 3,
            "channel_map": [1, 2, 3],
            "vad_enabled": True,
            "vad_threshold": 0.55,
            "vad_weight": 0.45,
            "confidence_smoothing": 0.35,
            "adaptive_noise_enabled": True,
            "adaptive_noise_alpha": 0.02,
            "noise_floor_min_db": -85,
            "noise_floor_max_db": -35,
            "transient_rejection_ms": 180,
            "disabled_channels": [],
            "level_offsets_db": [0, 0, 0],
            "bleed_pairs": [[1, 2], [2, 3]],
            "bleed_rejection_db": 6,
        },
        "people": [
            {"mic_channel": 1, "name": "A", "camera": 1, "preset": 1},
            {"mic_channel": 2, "name": "B", "camera": 1, "preset": 2},
            {"mic_channel": 3, "name": "C", "camera": 1, "preset": 3},
        ],
        "wide_shot": {"camera": 1, "preset": 20},
    }


def test_v07_detection_config_is_valid():
    validate_config(base_config())


@pytest.mark.parametrize("key", ["vad_threshold", "vad_weight", "confidence_smoothing", "adaptive_noise_alpha"])
def test_probabilities_and_smoothing_must_be_bounded(key):
    cfg = base_config()
    cfg["audio"][key] = 1.1
    with pytest.raises(ConfigError, match="between"):
        validate_config(cfg)


def test_level_offsets_must_match_logical_channel_count():
    cfg = base_config()
    cfg["audio"]["level_offsets_db"] = [0, 0]
    with pytest.raises(ConfigError, match="exactly 3"):
        validate_config(cfg)


@pytest.mark.parametrize("disabled", [[0], [4], [2, 2]])
def test_disabled_channels_are_validated(disabled):
    cfg = base_config()
    cfg["audio"]["disabled_channels"] = disabled
    with pytest.raises(ConfigError):
        validate_config(cfg)


@pytest.mark.parametrize("pairs", [[[1]], [[1, 1]], [[1, 4]], [[1, 2], [2, 1]]])
def test_bleed_relationships_are_validated(pairs):
    cfg = copy.deepcopy(base_config())
    cfg["audio"]["bleed_pairs"] = pairs
    with pytest.raises(ConfigError):
        validate_config(cfg)


def test_vad_boolean_is_not_accepted_as_a_string():
    cfg = base_config()
    cfg["audio"]["vad_enabled"] = "true"
    with pytest.raises(ConfigError, match="true or false"):
        validate_config(cfg)
