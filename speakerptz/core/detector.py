from __future__ import annotations

import statistics
import time
from dataclasses import dataclass
from typing import Iterable


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
    speech_probabilities: list[float]
    scores: list[float]
    reason: str
    overlap: bool


class ActiveSpeakerDetector:
    """Conservative active-speaker selector for isolated microphone channels.

    Selection combines each channel's signal above its own noise floor with an
    optional local VAD probability. It rejects configured neighbor bleed,
    ambiguous overlap, and brief transients before applying speaker-handoff
    hysteresis. It performs no transcription or speaker recognition.
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
        vad_enabled: bool = True,
        vad_threshold: float = 0.55,
        vad_weight: float = 0.45,
        confidence_smoothing: float = 0.35,
        transient_rejection_ms: int = 0,
        overlap_margin_db: float = 2.0,
        adaptive_noise_enabled: bool = True,
        adaptive_noise_alpha: float = 0.02,
        noise_floor_min_db: float = -85.0,
        noise_floor_max_db: float = -35.0,
        disabled_channels: Iterable[int] = (),
        level_offsets_db: Iterable[float] = (),
        bleed_pairs: Iterable[Iterable[int]] = (),
        bleed_rejection_db: float = 6.0,
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
        self.vad_enabled = bool(vad_enabled)
        self.vad_threshold = float(vad_threshold)
        self.vad_weight = self._clamp(float(vad_weight))
        self.confidence_smoothing = self._clamp(float(confidence_smoothing))
        self.transient_rejection = max(0, int(transient_rejection_ms)) / 1000.0
        self.overlap_margin_db = max(0.0, float(overlap_margin_db))
        self.adaptive_noise_enabled = bool(adaptive_noise_enabled)
        self.adaptive_noise_alpha = self._clamp(float(adaptive_noise_alpha))
        self.noise_floor_min_db = float(noise_floor_min_db)
        self.noise_floor_max_db = float(noise_floor_max_db)
        self.disabled_channels = {int(channel) for channel in disabled_channels}
        self.level_offsets_db = [float(value) for value in level_offsets_db]
        self.bleed_pairs = {
            tuple(sorted((int(pair[0]), int(pair[1]))))
            for pair in bleed_pairs
            if len(pair) == 2
        }
        self.bleed_rejection_db = max(0.0, float(bleed_rejection_db))

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
        self.speech_probabilities: list[float] = []
        self.scores: list[float] = []
        self.reason = "starting"
        self.overlap = False
        self._calibration_samples: list[list[float]] = []
        self._calibrated = self.calibration_seconds == 0.0

    @staticmethod
    def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, value))

    def _offset_levels(self, levels_db: list[float]) -> list[float]:
        return [
            float(level) + (self.level_offsets_db[index] if index < len(self.level_offsets_db) else 0.0)
            for index, level in enumerate(levels_db)
        ]

    def _finish_calibration(self, channels: int) -> None:
        if not self._calibration_samples:
            self.noise_floors = [-65.0] * channels
        else:
            self.noise_floors = []
            for channel in range(channels):
                samples = [row[channel] for row in self._calibration_samples if channel < len(row)]
                floor = float(statistics.median(samples)) if samples else -65.0
                self.noise_floors.append(self._clamp_floor(floor))
        self._calibration_samples.clear()
        self._calibrated = True

    def _clamp_floor(self, value: float) -> float:
        return max(self.noise_floor_min_db, min(self.noise_floor_max_db, value))

    def _compute_confidence(self, best_snr: float, dominance: float, speech_probability: float) -> float:
        energy = self._clamp((best_snr - self.signal_margin_db) / 14.0)
        separation = self._clamp(dominance / 10.0)
        level_confidence = self._clamp(0.55 + 0.30 * energy + 0.15 * separation, 0.0, 0.99)
        return self._clamp(
            (1.0 - self.vad_weight) * level_confidence + self.vad_weight * speech_probability,
            0.0,
            0.99,
        )

    def _reject_neighbor_bleed(self) -> None:
        for first, second in self.bleed_pairs:
            a = first - 1
            b = second - 1
            if not (0 <= a < len(self.eligible) and 0 <= b < len(self.eligible)):
                continue
            if not (self.eligible[a] and self.eligible[b]):
                continue
            if self.snr_db[a] >= self.snr_db[b] + self.bleed_rejection_db:
                self.eligible[b] = False
            elif self.snr_db[b] >= self.snr_db[a] + self.bleed_rejection_db:
                self.eligible[a] = False

    def _adapt_noise_floors(self, levels: list[float]) -> None:
        if not self.adaptive_noise_enabled:
            return
        for index, level in enumerate(levels):
            if index >= len(self.noise_floors) or index >= len(self.speech_probabilities):
                continue
            channel = index + 1
            quiet = self.speech_probabilities[index] < self.vad_threshold
            below_gate = level < self.absolute_threshold_db or self.snr_db[index] < self.signal_margin_db
            if channel not in self.disabled_channels and quiet and below_gate:
                previous = self.noise_floors[index]
                updated = previous + self.adaptive_noise_alpha * (level - previous)
                self.noise_floors[index] = self._clamp_floor(updated)

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
            speech_probabilities=list(self.speech_probabilities),
            scores=list(self.scores),
            reason=self.reason,
            overlap=self.overlap,
        )

    def update(
        self,
        levels_db: list[float],
        now: float | None = None,
        speech_probabilities: list[float] | None = None,
    ):
        if not levels_db:
            self.reason = "no audio levels"
            return None

        current = time.monotonic() if now is None else float(now)
        levels = self._offset_levels(levels_db)
        channels = len(levels)
        just_calibrated = False

        if not self._calibrated:
            self._calibration_samples.append(levels)
            if current - self.started < self.calibration_seconds:
                self.confidence = 0.0
                self.reason = "calibrating room noise"
                return None
            self._finish_calibration(channels)
            self.last_speech = current
            just_calibrated = True

        if len(self.noise_floors) != channels:
            self.noise_floors = [-65.0] * channels

        self.snr_db = [levels[index] - self.noise_floors[index] for index in range(channels)]
        vad_supplied = speech_probabilities is not None
        if vad_supplied and len(speech_probabilities) != channels:
            self.eligible = [False] * channels
            self.speech_probabilities = [0.0] * channels
            self.scores = [-999.0] * channels
            self.candidate = None
            self.confidence = 0.0
            self.reason = "VAD channel count mismatch; movement suppressed"
            return None

        if vad_supplied:
            self.speech_probabilities = [self._clamp(float(value)) for value in speech_probabilities]
        else:
            self.speech_probabilities = [
                1.0 if levels[index] >= self.absolute_threshold_db and self.snr_db[index] >= self.signal_margin_db else 0.0
                for index in range(channels)
            ]

        self.eligible = []
        for index in range(channels):
            energy_ok = levels[index] >= self.absolute_threshold_db and self.snr_db[index] >= self.signal_margin_db
            vad_ok = not (self.vad_enabled and vad_supplied) or self.speech_probabilities[index] >= self.vad_threshold
            enabled = index + 1 not in self.disabled_channels
            self.eligible.append(enabled and energy_ok and vad_ok)

        self._reject_neighbor_bleed()
        self.scores = [
            self.snr_db[index] + (10.0 * self.vad_weight * (self.speech_probabilities[index] - 0.5))
            if self.eligible[index]
            else -999.0
            for index in range(channels)
        ]
        eligible_indices = [index for index, ok in enumerate(self.eligible) if ok]
        if not just_calibrated:
            self._adapt_noise_floors(levels)
        event = None
        self.overlap = False

        if eligible_indices:
            ranked = sorted(eligible_indices, key=lambda index: self.scores[index], reverse=True)
            best_idx = ranked[0]
            best_ch = best_idx + 1
            best_score = self.scores[best_idx]
            second_score = self.scores[ranked[1]] if len(ranked) > 1 else 0.0
            dominance = best_score - second_score
            self.last_speech = current

            if len(ranked) > 1 and dominance < self.overlap_margin_db:
                self.overlap = True
                if self.active is None or self.active - 1 not in ranked[:2]:
                    self.candidate = None
                    self.confidence = 0.0
                    self.reason = "ambiguous overlapping speech; no camera move"
                    return None
                best_ch = self.active
                best_idx = self.active - 1
                best_score = self.scores[best_idx]
                dominance = max(0.0, best_score - second_score)
                self.reason = f"overlap detected; holding mic {self.active}"

            if self.active is not None and self.active != best_ch:
                active_idx = self.active - 1
                active_score = self.scores[active_idx] if 0 <= active_idx < channels else -999.0
                active_is_eligible = self.eligible[active_idx] if 0 <= active_idx < channels else False
                if active_is_eligible and best_score < active_score + self.dominance_margin_db:
                    best_ch = self.active
                    best_idx = active_idx
                    best_score = active_score
                    self.reason = f"current-speaker hysteresis; holding mic {self.active}"

            raw_confidence = self._compute_confidence(
                self.snr_db[best_idx],
                max(0.0, dominance),
                self.speech_probabilities[best_idx],
            )
            if self.candidate != best_ch:
                self.candidate = best_ch
                self.candidate_since = current
                self.confidence = raw_confidence
            else:
                alpha = self.confidence_smoothing
                self.confidence += alpha * (raw_confidence - self.confidence)

            required_delay = (
                max(self.initial_activation, self.transient_rejection)
                if self.active is None
                else max(self.switch_delay, self.transient_rejection)
            )
            candidate_age = current - self.candidate_since

            if self.confidence < self.confidence_min:
                self.reason = f"mic {best_ch} confidence below threshold"
            elif candidate_age < required_delay:
                self.reason = f"mic {best_ch} confirming speech ({candidate_age:.2f}/{required_delay:.2f}s)"
            elif self.active is None:
                self.active = best_ch
                self.active_since = current
                self.reason = f"mic {best_ch} confirmed as active speaker"
                event = ("speaker", self.active)
            elif self.active != best_ch and current - self.active_since >= self.hold_time:
                previous = self.active
                self.active = best_ch
                self.active_since = current
                self.reason = f"sustained handoff from mic {previous} to mic {best_ch}"
                event = ("speaker", self.active)
            elif self.active == best_ch and not self.overlap:
                self.reason = f"mic {best_ch} remains active"

        else:
            self.candidate = None
            self.confidence = 0.0
            if self.active is not None and current - self.last_speech >= self.silence_timeout:
                previous = self.active
                self.active = None
                self.reason = f"silence timeout after mic {previous}; request wide shot"
                event = ("silence", None)
            else:
                self.reason = "no channel contains confident speech"

        return event
