from __future__ import annotations

import statistics
import time
from dataclasses import dataclass


@dataclass
class DetectorSnapshot:
    active: int | None
    candidate: int | None
    confidence: float
    calibrating: bool
    calibration_remaining: float
    noise_floors: list[float]
    snr_db: list[float]
    eligible: list[bool]


class ActiveSpeakerDetector:
    """Noise-floor-aware active-speaker detector.

    The detector intentionally does not attempt speaker recognition. It assumes
    each input channel belongs to a known seat/person and selects the channel
    whose signal is most convincingly above its own calibrated background.
    """

    def __init__(
        self,
        absolute_threshold_db: float = -50.0,
        signal_margin_db: float = 8.0,
        dominance_margin_db: float = 3.0,
        initial_activation_ms: int = 250,
        switch_delay_ms: int = 650,
        hold_time_ms: int = 1200,
        silence_timeout_ms: int = 5000,
        calibration_seconds: float = 3.0,
        confidence_min: float = 0.55,
        now: float | None = None,
    ):
        self.absolute_threshold_db = float(absolute_threshold_db)
        self.signal_margin_db = float(signal_margin_db)
        self.dominance_margin_db = float(dominance_margin_db)
        self.initial_activation = initial_activation_ms / 1000.0
        self.switch_delay = switch_delay_ms / 1000.0
        self.hold_time = hold_time_ms / 1000.0
        self.silence_timeout = silence_timeout_ms / 1000.0
        self.calibration_seconds = max(0.0, float(calibration_seconds))
        self.confidence_min = float(confidence_min)

        start = time.monotonic() if now is None else float(now)
        self.started = start
        self.last_speech = start
        self.candidate: int | None = None
        self.candidate_since = start
        self.active: int | None = None
        self.active_since = start
        self.confidence = 0.0
        self.noise_floors: list[float] = []
        self.snr_db: list[float] = []
        self.eligible: list[bool] = []
        self._calibration_samples: list[list[float]] = []
        self._calibrated = self.calibration_seconds == 0.0

    @staticmethod
    def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, value))

    def _finish_calibration(self, channels: int) -> None:
        if not self._calibration_samples:
            self.noise_floors = [-65.0] * channels
        else:
            self.noise_floors = []
            for ch in range(channels):
                samples = [row[ch] for row in self._calibration_samples if ch < len(row)]
                # Median is intentionally robust against an occasional click/noise.
                self.noise_floors.append(float(statistics.median(samples)) if samples else -65.0)
        self._calibration_samples.clear()
        self._calibrated = True

    def _compute_confidence(self, best_snr: float, dominance: float) -> float:
        energy = self._clamp((best_snr - self.signal_margin_db) / 14.0)
        separation = self._clamp(dominance / 10.0)
        # A valid speech candidate starts around 0.55 and rises with strength/separation.
        return self._clamp(0.55 + 0.30 * energy + 0.15 * separation, 0.0, 0.99)

    def snapshot(self, now: float | None = None) -> DetectorSnapshot:
        current = time.monotonic() if now is None else float(now)
        remaining = max(0.0, self.calibration_seconds - (current - self.started)) if not self._calibrated else 0.0
        return DetectorSnapshot(
            active=self.active,
            candidate=self.candidate,
            confidence=self.confidence,
            calibrating=not self._calibrated,
            calibration_remaining=remaining,
            noise_floors=list(self.noise_floors),
            snr_db=list(self.snr_db),
            eligible=list(self.eligible),
        )

    def update(self, levels_db: list[float], now: float | None = None):
        if not levels_db:
            return None

        current = time.monotonic() if now is None else float(now)
        channels = len(levels_db)

        if not self._calibrated:
            self._calibration_samples.append([float(x) for x in levels_db])
            if current - self.started < self.calibration_seconds:
                self.confidence = 0.0
                return None
            self._finish_calibration(channels)
            self.last_speech = current

        if len(self.noise_floors) != channels:
            # Safe fallback for a channel-count change after startup.
            self.noise_floors = [-65.0] * channels

        self.snr_db = [float(levels_db[i]) - self.noise_floors[i] for i in range(channels)]
        self.eligible = [
            float(levels_db[i]) >= self.absolute_threshold_db and self.snr_db[i] >= self.signal_margin_db
            for i in range(channels)
        ]

        eligible_indices = [i for i, ok in enumerate(self.eligible) if ok]
        event = None

        if eligible_indices:
            # Select by rise above that mic's own floor, not raw loudness.
            best_idx = max(eligible_indices, key=lambda i: self.snr_db[i])
            best_ch = best_idx + 1
            best_snr = self.snr_db[best_idx]
            competing = [self.snr_db[i] for i in eligible_indices if i != best_idx]
            second_snr = max(competing) if competing else 0.0
            dominance = best_snr - second_snr
            self.confidence = self._compute_confidence(best_snr, dominance)
            self.last_speech = current

            # If an active speaker exists, do not hand off for tiny differences.
            if self.active is not None and self.active != best_ch:
                active_idx = self.active - 1
                active_snr = self.snr_db[active_idx] if 0 <= active_idx < channels else -999.0
                active_is_eligible = self.eligible[active_idx] if 0 <= active_idx < channels else False
                if active_is_eligible and best_snr < active_snr + self.dominance_margin_db:
                    best_ch = self.active
                    best_idx = active_idx

            if self.candidate != best_ch:
                self.candidate = best_ch
                self.candidate_since = current

            required_delay = self.initial_activation if self.active is None else self.switch_delay
            candidate_age = current - self.candidate_since

            if self.confidence >= self.confidence_min and candidate_age >= required_delay:
                if self.active is None:
                    self.active = best_ch
                    self.active_since = current
                    event = ("speaker", self.active)
                elif self.active != best_ch and current - self.active_since >= self.hold_time:
                    self.active = best_ch
                    self.active_since = current
                    event = ("speaker", self.active)
        else:
            self.candidate = None
            self.confidence = 0.0
            if self.active is not None and current - self.last_speech >= self.silence_timeout:
                self.active = None
                event = ("silence", None)

        return event
