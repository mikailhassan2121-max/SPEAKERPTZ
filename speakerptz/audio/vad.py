from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class AudioObservation:
    """One privacy-preserving analysis frame.

    Only levels and speech probabilities leave the audio callback. Raw samples
    are neither queued nor written to disk.
    """

    levels_db: list[float]
    speech_probabilities: list[float]


class VoiceActivityAnalyzer:
    """Lightweight local VAD for isolated boardroom microphone channels.

    The analyzer combines energy, zero-crossing rate, speech-band energy, and
    spectral shape. It is deliberately conservative: one-sample impulses and
    broadband hiss should not look like sustained speech. This is not speech
    recognition and does not retain audio.
    """

    def __init__(
        self,
        sample_rate: int,
        channels: int,
        attack: float = 0.45,
        release: float = 0.18,
        energy_floor_db: float = -65.0,
    ):
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.attack = self._clamp(float(attack))
        self.release = self._clamp(float(release))
        self.energy_floor_db = float(energy_floor_db)
        self._smoothed = [0.0] * self.channels

    @staticmethod
    def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, value))

    @staticmethod
    def _rms_db(samples: np.ndarray) -> float:
        rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
        if rms < 1e-9:
            return -100.0
        return max(-100.0, 20.0 * float(np.log10(rms)))

    def _probability(self, samples: np.ndarray, level_db: float) -> float:
        x = np.asarray(samples, dtype=np.float64)
        if x.size < 16 or level_db <= self.energy_floor_db:
            return 0.0

        x = x - float(np.mean(x))
        rms = float(np.sqrt(np.mean(np.square(x))))
        if rms < 1e-9:
            return 0.0

        peak = float(np.max(np.abs(x)))
        crest = peak / rms
        signs = np.signbit(x)
        zcr = float(np.mean(signs[1:] != signs[:-1]))

        windowed = x * np.hanning(x.size)
        power = np.square(np.abs(np.fft.rfft(windowed))) + 1e-12
        frequencies = np.fft.rfftfreq(x.size, 1.0 / self.sample_rate)
        speech_band = (frequencies >= 120.0) & (frequencies <= 4000.0)
        band_ratio = float(np.sum(power[speech_band]) / np.sum(power))
        flatness = float(np.exp(np.mean(np.log(power))) / np.mean(power))

        energy = self._clamp((level_db - self.energy_floor_db) / 35.0)
        if zcr < 0.008:
            zcr_score = self._clamp(zcr / 0.008)
        elif zcr <= 0.30:
            zcr_score = 1.0
        else:
            zcr_score = self._clamp((0.50 - zcr) / 0.20)
        band_score = self._clamp((band_ratio - 0.20) / 0.70)
        structure = self._clamp(1.0 - flatness)

        probability = 0.50 * energy + 0.22 * zcr_score + 0.23 * band_score + 0.05 * structure
        # A sharp tap/impact has a much higher crest factor than a normal voice
        # frame. Sustained speech in following frames will recover immediately.
        if crest > 7.0:
            probability *= 0.35
        return self._clamp(probability)

    def analyze(self, samples: np.ndarray) -> AudioObservation:
        frame = np.asarray(samples, dtype=np.float64)
        if frame.ndim == 1:
            frame = frame[:, np.newaxis]
        if frame.ndim != 2 or frame.shape[1] != self.channels:
            raise ValueError(f"VAD expected {self.channels} channels, got shape {frame.shape}.")

        levels: list[float] = []
        probabilities: list[float] = []
        for channel in range(self.channels):
            channel_samples = frame[:, channel]
            level = self._rms_db(channel_samples)
            raw = self._probability(channel_samples, level)
            previous = self._smoothed[channel]
            factor = self.attack if raw >= previous else self.release
            smoothed = previous + factor * (raw - previous)
            self._smoothed[channel] = self._clamp(smoothed)
            levels.append(level)
            probabilities.append(self._smoothed[channel])
        return AudioObservation(levels, probabilities)
