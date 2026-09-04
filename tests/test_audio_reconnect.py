import importlib
import sys
from types import SimpleNamespace


class FakeStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


def test_real_audio_restart_reopens_same_bounded_configuration(monkeypatch):
    streams = []

    def factory(**kwargs):
        stream = FakeStream(**kwargs)
        streams.append(stream)
        return stream

    fake_sounddevice = SimpleNamespace(InputStream=factory)
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sounddevice)
    sys.modules.pop("speakerptz.audio.realtime", None)
    realtime = importlib.import_module("speakerptz.audio.realtime")
    source = realtime.RealAudioSource(device=4, channels=2, sample_rate=48000, channel_map=[1, 2])
    source.start()
    source.restart()

    assert len(streams) == 2
    assert streams[0].stopped and streams[0].closed
    assert streams[1].started
    assert streams[1].kwargs["device"] == 4
    assert streams[1].kwargs["channels"] == 2
    assert streams[1].kwargs["samplerate"] == 48000
    assert source.callback_count == 0
