import math
import random
import time

from .vad import AudioObservation


class SimulatedAudioSource:
    """Simulation includes startup room noise and realistic adjacent-mic bleed."""

    def __init__(self, channels: int):
        self.channels = int(channels)
        self.started = time.monotonic()

    def read_observation(self) -> AudioObservation:
        t = time.monotonic() - self.started
        # First 3.5 seconds are intentionally quiet for auto-calibration.
        if t < 3.5:
            return AudioObservation(
                [random.uniform(-65, -56) for _ in range(self.channels)],
                [random.uniform(0.0, 0.08) for _ in range(self.channels)],
            )

        active = int((t - 3.5) // 5) % self.channels
        levels = []
        speech_probabilities = []
        for i in range(self.channels):
            noise = random.uniform(-65, -55)
            if i == active:
                speech = -21 + 3 * math.sin(t * 3.1) + random.uniform(-2, 2)
                levels.append(speech)
                speech_probabilities.append(random.uniform(0.82, 0.97))
            elif abs(i - active) == 1:
                # Simulated crosstalk/bleed from a neighboring gooseneck mic.
                levels.append(random.uniform(-39, -33))
                speech_probabilities.append(random.uniform(0.18, 0.38))
            else:
                levels.append(noise)
                speech_probabilities.append(random.uniform(0.0, 0.08))
        return AudioObservation(levels, speech_probabilities)

    def read_levels(self) -> list[float]:
        return self.read_observation().levels_db
