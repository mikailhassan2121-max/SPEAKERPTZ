import pytest

from speakerptz.core.config import ConfigError, validate_config


def config_with_dashboard(host="127.0.0.1", allow_remote=False):
    return {
        "runtime": {"mode": "simulate"},
        "dashboard": {
            "enabled": True,
            "host": host,
            "port": 8765,
            "allow_remote": allow_remote,
        },
        "audio": {"channels": 1, "channel_map": [1]},
        "people": [{"mic_channel": 1, "name": "A", "camera": 1, "preset": 1}],
        "wide_shot": {"camera": 1, "preset": 20},
    }


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_dashboard_hosts_are_valid(host):
    validate_config(config_with_dashboard(host))


@pytest.mark.parametrize("host", ["0.0.0.0", "192.0.2.10", "operator-room.local"])
def test_non_loopback_dashboard_is_rejected_by_default(host):
    with pytest.raises(ConfigError, match="allow_remote"):
        validate_config(config_with_dashboard(host))


def test_remote_dashboard_requires_explicit_boolean_opt_in():
    validate_config(config_with_dashboard("0.0.0.0", allow_remote=True))
    cfg = config_with_dashboard()
    cfg["dashboard"]["allow_remote"] = "true"
    with pytest.raises(ConfigError, match="true or false"):
        validate_config(cfg)


@pytest.mark.parametrize("port", [0, 65536])
def test_dashboard_port_is_bounded(port):
    cfg = config_with_dashboard()
    cfg["dashboard"]["port"] = port
    with pytest.raises(ConfigError, match="port"):
        validate_config(cfg)

