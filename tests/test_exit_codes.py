import pytest

import speakerptz.main as main_module


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("CONFIG ERROR: bad config", 2),
        ("AUDIO DEVICE ERROR: missing", 3),
        ("CAMERA PROBE BLOCKED: safety", 4),
        ("DASHBOARD STARTUP ERROR: port busy", 5),
        ("INSTANCE ERROR: already running", 6),
        ("unexpected controlled exit", 1),
    ],
)
def test_cli_maps_controlled_failures_to_deterministic_codes(monkeypatch, capsys, message, expected):
    def fail():
        raise SystemExit(message)

    monkeypatch.setattr(main_module, "main", fail)
    assert main_module.cli() == expected
    assert message in capsys.readouterr().err


def test_cli_preserves_explicit_integer_exit(monkeypatch):
    def fail():
        raise SystemExit(7)

    monkeypatch.setattr(main_module, "main", fail)
    assert main_module.cli() == 7

