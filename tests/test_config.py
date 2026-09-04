from speakerptz.core.config import validate_config, ConfigError


def base_config():
    return {
        "runtime": {"mode": "simulate"},
        "audio": {"channels": 2, "channel_map": [1, 2]},
        "people": [
            {"mic_channel": 1, "name": "A", "camera": 1, "preset": 1},
            {"mic_channel": 2, "name": "B", "camera": 1, "preset": 2},
        ],
        "wide_shot": {"camera": 1, "preset": 20},
    }


def test_valid_config_passes():
    validate_config(base_config())


def test_duplicate_mic_rejected():
    cfg = base_config()
    cfg["people"][1]["mic_channel"] = 1
    try:
        validate_config(cfg)
    except ConfigError as exc:
        assert "Duplicate mic_channel" in str(exc)
    else:
        raise AssertionError("expected ConfigError")


def test_out_of_range_mic_rejected():
    cfg = base_config()
    cfg["people"][1]["mic_channel"] = 3
    try:
        validate_config(cfg)
    except ConfigError as exc:
        assert "exceeds configured" in str(exc)
    else:
        raise AssertionError("expected ConfigError")



def test_channel_map_length_rejected():
    cfg = base_config()
    cfg["audio"]["channel_map"] = [1]
    try:
        validate_config(cfg)
    except ConfigError as exc:
        assert "channel_map" in str(exc)
    else:
        raise AssertionError("expected ConfigError")


def test_sparse_channel_map_is_valid():
    cfg = base_config()
    cfg["audio"]["channel_map"] = [5, 9]
    validate_config(cfg)
