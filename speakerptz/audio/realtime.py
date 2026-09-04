from __future__ import annotations

import queue
import time
from dataclasses import dataclass
import numpy as np
import sounddevice as sd

from .channelmap import normalize_channel_map, required_physical_channels
from .vad import AudioObservation, VoiceActivityAnalyzer


@dataclass(frozen=True)
class AudioHealth:
    ok: bool
    stale_seconds: float
    callback_status: str


class RealAudioSource:
    def __init__(
        self,
        device,
        channels: int,
        sample_rate: int,
        blocksize: int = 1024,
        channel_map=None,
    ):
        self.device = device
        self.channels = int(channels)
        self.sample_rate = int(sample_rate)
        self.blocksize = int(blocksize)
        self.channel_map = normalize_channel_map(channel_map, self.channels)
        self.physical_channels = required_physical_channels(self.channel_map)
        self._indices = [v - 1 for v in self.channel_map]
        self._q: queue.Queue[AudioObservation] = queue.Queue(maxsize=8)
        self._last = AudioObservation([-100.0] * self.channels, [0.0] * self.channels)
        self._vad = VoiceActivityAnalyzer(self.sample_rate, self.channels)
        self._last_callback = 0.0
        self._callback_count = 0
        self._last_status = ""
        self._stream = self._create_stream()

    def _create_stream(self):
        return sd.InputStream(
            device=self.device,
            channels=self.physical_channels,
            samplerate=self.sample_rate,
            blocksize=self.blocksize,
            dtype="float32",
            callback=self._callback,
        )

    @staticmethod
    def _rms_db(x: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))
        if rms < 1e-9:
            return -100.0
        return max(-100.0, 20.0 * float(np.log10(rms)))

    def _callback(self, indata, frames, time_info, status):
        self._last_callback = time.monotonic()
        self._callback_count += 1
        self._last_status = str(status) if status else ""
        logical_samples = np.asarray(indata[:, self._indices], dtype=np.float64)
        observation = self._vad.analyze(logical_samples)
        try:
            self._q.put_nowait(observation)
        except queue.Full:
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._q.put_nowait(observation)
            except queue.Full:
                pass

    def start(self):
        self._stream.start()
        self._last_callback = time.monotonic()

    def stop(self):
        self._stream.stop()
        self._stream.close()

    def restart(self):
        """Reopen the same configured device; callers provide attempt bounds."""
        try:
            self._stream.stop()
        except Exception:
            pass
        try:
            self._stream.close()
        except Exception:
            pass
        self._stream = self._create_stream()
        self._q = queue.Queue(maxsize=8)
        self._last = AudioObservation([-100.0] * self.channels, [0.0] * self.channels)
        self._last_status = ""
        self.start()

    def read_observation(self) -> AudioObservation:
        try:
            while True:
                self._last = self._q.get_nowait()
        except queue.Empty:
            pass
        return self._last

    def read_levels(self):
        return self.read_observation().levels_db

    def health(self, stale_after: float = 1.5) -> AudioHealth:
        age = max(0.0, time.monotonic() - self._last_callback)
        return AudioHealth(ok=age <= float(stale_after), stale_seconds=age, callback_status=self._last_status)

    @property
    def callback_count(self) -> int:
        return self._callback_count
