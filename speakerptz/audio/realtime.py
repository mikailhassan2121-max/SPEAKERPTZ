import queue
import numpy as np
import sounddevice as sd


class RealAudioSource:
    def __init__(self, device, channels: int, sample_rate: int, blocksize: int = 1024):
        self.device = device
        self.channels = int(channels)
        self.sample_rate = int(sample_rate)
        self.blocksize = int(blocksize)
        self._q: queue.Queue[list[float]] = queue.Queue(maxsize=8)
        self._last = [-100.0] * self.channels
        self._stream = sd.InputStream(
            device=self.device,
            channels=self.channels,
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
        levels = [self._rms_db(indata[:, ch]) for ch in range(self.channels)]
        try:
            self._q.put_nowait(levels)
        except queue.Full:
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._q.put_nowait(levels)
            except queue.Full:
                pass

    def start(self):
        self._stream.start()

    def stop(self):
        self._stream.stop()
        self._stream.close()

    def read_levels(self):
        try:
            while True:
                self._last = self._q.get_nowait()
        except queue.Empty:
            pass
        return self._last
