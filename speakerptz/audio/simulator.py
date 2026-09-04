import math
import random
import time


class SimulatedAudioSource:
    """Simulation includes startup room noise and realistic adjacent-mic bleed."""

    def __init__(self, channels: int):
        self.channels = int(channels)
        self.started = time.monotonic()

    def read_levels(self) -> list[float]:
        t = time.monotonic() - self.started
        # First 3.5 seconds are intentionally quiet for auto-calibration.
        if t < 3.5:
            return [random.uniform(-65, -56) for _ in range(self.channels)]

        active = int((t - 3.5) // 5) % self.channels
        levels = []
        for i in range(self.channels):
            noise = random.uniform(-65, -55)
            if i == active:
                speech = -21 + 3 * math.sin(t * 3.1) + random.uniform(-2, 2)
                levels.append(speech)
            elif abs(i - active) == 1:
                # Simulated crosstalk/bleed from a neighboring gooseneck mic.
                levels.append(random.uniform(-39, -33))
            else:
                levels.append(noise)
        return levels
