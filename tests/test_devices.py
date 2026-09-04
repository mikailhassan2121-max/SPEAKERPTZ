from speakerptz.audio.devices import resolve_input_device


class FakeSD:
    @staticmethod
    def query_devices():
        return [
            {"name": "Speakers", "max_input_channels": 0, "hostapi": 0},
            {"name": "Microphone Array", "max_input_channels": 4, "hostapi": 0},
            {"name": "Dante Virtual Soundcard", "max_input_channels": 16, "hostapi": 1},
        ]


def test_device_name_resolution_prefers_matching_capable_input():
    d = resolve_input_device(device_name="dante virtual", channels=8, sd_module=FakeSD)
    assert d.index == 2
    assert d.max_input_channels == 16


def test_device_index_resolution():
    d = resolve_input_device(device_index=1, channels=4, sd_module=FakeSD)
    assert d.name == "Microphone Array"


def test_device_rejects_too_many_channels():
    try:
        resolve_input_device(device_index=1, channels=8, sd_module=FakeSD)
    except ValueError as exc:
        assert "exposes 4 input channel" in str(exc)
    else:
        raise AssertionError("expected ValueError")
