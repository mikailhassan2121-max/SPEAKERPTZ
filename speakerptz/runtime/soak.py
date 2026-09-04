from __future__ import annotations

import random
from dataclasses import asdict, dataclass

from speakerptz.cameras.base import CameraConnectionError, CameraDriver
from speakerptz.cameras.manager import CameraManager
from speakerptz.cameras.models import CameraConfig, CameraHealth, CameraState
from speakerptz.core.detector import ActiveSpeakerDetector


class _SoakCamera(CameraDriver):
    def __init__(self):
        self.connected = False
        self.fail_connect = False
        self.moves = 0
        self.stops = 0

    def connect(self):
        if self.fail_connect:
            raise CameraConnectionError("injected soak-test camera failure")
        self.connected = True

    def health(self):
        return CameraHealth(
            CameraState.READY if self.connected else CameraState.ERROR,
            connected=self.connected,
        )

    def goto_preset(self, preset, label=""):
        if not self.connected:
            raise CameraConnectionError("camera disconnected")
        self.moves += 1

    def stop(self):
        self.stops += 1

    def home(self):
        return None

    def disconnect(self):
        self.connected = False


@dataclass
class SoakSummary:
    iterations: int
    seed: int
    speaker_events: int = 0
    silence_events: int = 0
    overlap_frames: int = 0
    audio_dropouts: int = 0
    camera_failures: int = 0
    accepted_moves: int = 0
    safely_blocked_moves: int = 0
    emergency_stops: int = 0
    invariant_failures: int = 0


def run_soak_test(iterations: int = 5000, channels: int = 4, seed: int = 17) -> dict:
    iterations = max(100, int(iterations))
    channels = max(2, int(channels))
    randomizer = random.Random(seed)
    driver = _SoakCamera()
    now = [0.0]
    manager = CameraManager(
        [CameraConfig(1, "Soak simulator")],
        real_control_enabled=False,
        command_interval_seconds=0,
        movement_cooldown_seconds=0,
        reconnect_interval_seconds=0.1,
        reconnect_attempt_limit=3,
        clock=lambda: now[0],
        driver_factories={"simulator": lambda cfg: driver},
    )
    manager.connect_all()
    detector = ActiveSpeakerDetector(
        absolute_threshold_db=-50,
        signal_margin_db=8,
        initial_activation_ms=0,
        switch_delay_ms=0,
        hold_time_ms=0,
        silence_timeout_ms=250,
        calibration_seconds=0,
        transient_rejection_ms=0,
        overlap_margin_db=2,
        adaptive_noise_enabled=False,
        now=0,
    )
    detector.noise_floors = [-62.0] * channels
    summary = SoakSummary(iterations=iterations, seed=seed)

    for index in range(iterations):
        now[0] = index * 0.1
        phase = index % 25
        levels = [-68.0] * channels
        probabilities = [0.02] * channels

        if phase <= 11 or phase in {21, 24}:
            speaker = (index // 3) % channels
            levels[speaker] = -18.0 + randomizer.uniform(-2.0, 2.0)
            probabilities[speaker] = randomizer.uniform(0.82, 0.98)
        elif phase <= 14:
            first = (index // 5) % channels
            second = (first + 1) % channels
            levels[first] = -20.0
            levels[second] = -20.4
            probabilities[first] = probabilities[second] = 0.90
            summary.overlap_frames += 1
        elif phase <= 18:
            pass
        elif phase == 19:
            summary.audio_dropouts += 1
            continue
        elif phase == 20:
            driver.connected = False
            driver.fail_connect = True
            summary.camera_failures += 1
            speaker = (index // 3) % channels
            levels[speaker] = -18.0
            probabilities[speaker] = 0.95
        elif phase == 22:
            manager.emergency_stop()
            summary.emergency_stops += 1
            blocked = manager.goto_preset(1, 1)
            if blocked.accepted:
                summary.invariant_failures += 1
            else:
                summary.safely_blocked_moves += 1
            continue
        elif phase == 23:
            manager.clear_emergency_stop()

        if phase == 21:
            driver.fail_connect = False
            manager.maintain_health()

        event = detector.update(levels, now=now[0], speech_probabilities=probabilities)
        if not event:
            continue
        kind, channel = event
        if kind == "speaker":
            summary.speaker_events += 1
            result = manager.goto_preset(1, int(channel))
        else:
            summary.silence_events += 1
            result = manager.goto_preset(1, 20)
        if result.accepted:
            summary.accepted_moves += 1
            if not driver.connected or manager.emergency_stopped:
                summary.invariant_failures += 1
        else:
            summary.safely_blocked_moves += 1

    manager.emergency_stop()
    manager.disconnect_all()
    result = asdict(summary)
    result["passed"] = summary.invariant_failures == 0 and summary.speaker_events > 0 and summary.silence_events > 0
    return result
