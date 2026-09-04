from __future__ import annotations

import statistics
from dataclasses import dataclass, field


# Derived-value-only calibration. Levels arrive as dBFS numbers that were
# already computed inside the audio callback; raw samples never reach this
# module and are never written to disk.

DEAD_CHANNEL_DB = -90.0
MIN_USEFUL_SNR_DB = 10.0
HOT_CHANNEL_DB = -6.0
BLEED_SEPARATION_DB = 12.0
BLEED_ACTIVITY_DB = 6.0


@dataclass(frozen=True)
class ChannelCalibration:
    channel: int
    physical_input: int
    name: str
    noise_floor_db: float | None
    speech_level_db: float | None
    snr_db: float | None
    noise_frames: int
    speech_frames: int
    status: str
    notes: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        return self.status in {"ok", "hot"}

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "physical_input": self.physical_input,
            "name": self.name,
            "noise_floor_db": self.noise_floor_db,
            "speech_level_db": self.speech_level_db,
            "snr_db": self.snr_db,
            "noise_frames": self.noise_frames,
            "speech_frames": self.speech_frames,
            "status": self.status,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class RoomCalibration:
    channels: tuple[ChannelCalibration, ...]
    room_noise_floor_db: float | None
    suspected_bleed_pairs: tuple[tuple[int, int], ...]
    dead_channels: tuple[int, ...]
    unverified_channels: tuple[int, ...]
    recommended: dict = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        """True when every channel has both a noise floor and a speech sample."""
        return bool(self.channels) and not self.unverified_channels

    def to_dict(self) -> dict:
        return {
            "channels": [channel.to_dict() for channel in self.channels],
            "room_noise_floor_db": self.room_noise_floor_db,
            "suspected_bleed_pairs": [list(pair) for pair in self.suspected_bleed_pairs],
            "dead_channels": list(self.dead_channels),
            "unverified_channels": list(self.unverified_channels),
            "recommended": dict(self.recommended),
            "warnings": list(self.warnings),
        }


def _median(values) -> float | None:
    values = [float(value) for value in values]
    return float(statistics.median(values)) if values else None


def _round(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(float(value), digits)


class CalibrationSession:
    """Accumulates per-channel level statistics for one guided calibration.

    Feed quiet-room frames with `add_noise_frame`, then, while one person speaks
    into one microphone, feed frames with `add_speech_frame(channel, levels)`.
    Only dB values are retained.
    """

    def __init__(
        self,
        channels: int,
        channel_map=None,
        names=None,
        *,
        dead_channel_db: float = DEAD_CHANNEL_DB,
        min_useful_snr_db: float = MIN_USEFUL_SNR_DB,
        hot_channel_db: float = HOT_CHANNEL_DB,
    ):
        self.channels = int(channels)
        if self.channels < 1:
            raise ValueError("Calibration needs at least one channel.")
        self.channel_map = list(channel_map) if channel_map else list(range(1, self.channels + 1))
        if len(self.channel_map) != self.channels:
            raise ValueError("channel_map length must match the channel count.")
        self.names = list(names) if names else [f"Seat {index}" for index in range(1, self.channels + 1)]
        if len(self.names) != self.channels:
            raise ValueError("names length must match the channel count.")
        self.dead_channel_db = float(dead_channel_db)
        self.min_useful_snr_db = float(min_useful_snr_db)
        self.hot_channel_db = float(hot_channel_db)

        self._noise: list[list[float]] = [[] for _ in range(self.channels)]
        # speech[target channel][observed channel] -> levels seen while the
        # target channel's microphone was the one being spoken into.
        self._speech: dict[int, list[list[float]]] = {}

    def _check_frame(self, levels) -> list[float]:
        values = [float(value) for value in levels]
        if len(values) != self.channels:
            raise ValueError(f"Calibration frame has {len(values)} channels; expected {self.channels}.")
        return values

    def add_noise_frame(self, levels) -> None:
        values = self._check_frame(levels)
        for index, value in enumerate(values):
            self._noise[index].append(value)

    def add_speech_frame(self, channel: int, levels) -> None:
        channel = int(channel)
        if not 1 <= channel <= self.channels:
            raise ValueError(f"Speech channel {channel} is outside 1..{self.channels}.")
        values = self._check_frame(levels)
        buckets = self._speech.setdefault(channel, [[] for _ in range(self.channels)])
        for index, value in enumerate(values):
            buckets[index].append(value)

    @property
    def noise_frame_count(self) -> int:
        return len(self._noise[0]) if self._noise else 0

    def speech_frame_count(self, channel: int) -> int:
        buckets = self._speech.get(int(channel))
        return len(buckets[0]) if buckets else 0

    def _bleed_pairs(self, floors, speech_levels) -> list[tuple[int, int]]:
        pairs: set[tuple[int, int]] = set()
        for channel, buckets in self._speech.items():
            talker_level = speech_levels.get(channel)
            if talker_level is None:
                continue
            for index, samples in enumerate(buckets):
                neighbour = index + 1
                if neighbour == channel or not samples:
                    continue
                observed = _median(samples)
                floor = floors[index]
                if observed is None or floor is None:
                    continue
                if observed - floor < BLEED_ACTIVITY_DB:
                    continue
                if talker_level - observed <= BLEED_SEPARATION_DB:
                    pairs.add(tuple(sorted((channel, neighbour))))
        return sorted(pairs)

    def result(self) -> RoomCalibration:
        floors = [_median(samples) for samples in self._noise]
        speech_levels: dict[int, float] = {}
        for channel, buckets in self._speech.items():
            own = _median(buckets[channel - 1])
            if own is not None:
                speech_levels[channel] = own

        rows: list[ChannelCalibration] = []
        dead: list[int] = []
        unverified: list[int] = []
        warnings: list[str] = []

        for index in range(self.channels):
            channel = index + 1
            floor = floors[index]
            speech = speech_levels.get(channel)
            snr = None if (floor is None or speech is None) else speech - floor
            notes: list[str] = []

            if speech is None:
                status = "no_speech"
                notes.append("No speech sample was captured for this channel.")
                unverified.append(channel)
            elif speech <= self.dead_channel_db:
                status = "dead"
                notes.append(
                    "Speaking into this mic produced no signal above the noise floor; "
                    "the DVS input looks unsubscribed or muted."
                )
                dead.append(channel)
            elif floor is None:
                status = "no_noise_floor"
                notes.append("No quiet-room sample was captured for this channel.")
                unverified.append(channel)
            elif snr is not None and snr < self.min_useful_snr_db:
                status = "low_snr"
                notes.append(
                    f"Speech is only {snr:.1f} dB above this channel's noise floor; "
                    f"{self.min_useful_snr_db:.0f} dB or more is recommended."
                )
            elif speech >= self.hot_channel_db:
                status = "hot"
                notes.append("Speech level is close to clipping; reduce gain at the console.")
            else:
                status = "ok"

            rows.append(
                ChannelCalibration(
                    channel=channel,
                    physical_input=int(self.channel_map[index]),
                    name=str(self.names[index]),
                    noise_floor_db=_round(floor),
                    speech_level_db=_round(speech),
                    snr_db=_round(snr),
                    noise_frames=len(self._noise[index]),
                    speech_frames=self.speech_frame_count(channel),
                    status=status,
                    notes=tuple(notes),
                )
            )

        live_floors = [value for value in floors if value is not None and value > self.dead_channel_db]
        room_floor = _median(live_floors)
        bleed = self._bleed_pairs(floors, speech_levels)

        recommended: dict = {}
        if live_floors:
            worst_floor = max(live_floors)
            recommended["absolute_threshold_db"] = round(max(-70.0, min(-30.0, worst_floor + 6.0)), 1)
        observed_snrs = [row.snr_db for row in rows if row.snr_db is not None]
        if observed_snrs:
            recommended["signal_margin_db"] = round(max(6.0, min(14.0, min(observed_snrs) * 0.5)), 1)
        if speech_levels:
            target = _median(list(speech_levels.values()))
            offsets = []
            for index in range(self.channels):
                level = speech_levels.get(index + 1)
                offsets.append(0.0 if level is None else round(max(-12.0, min(12.0, target - level)), 1))
            recommended["level_offsets_db"] = offsets
        if dead:
            recommended["disabled_channels"] = list(dead)
        if bleed:
            recommended["bleed_pairs"] = [list(pair) for pair in bleed]

        if self.noise_frame_count == 0:
            warnings.append("No quiet-room frames were captured; noise floors are unknown.")
        if unverified:
            warnings.append(
                "Channels without a verified speech sample: "
                + ", ".join(str(channel) for channel in unverified)
            )
        if dead:
            warnings.append("Dead/unsubscribed channels: " + ", ".join(str(channel) for channel in dead))
        for row in rows:
            if row.status == "low_snr":
                warnings.append(f"Channel {row.channel} ({row.name}) has a low speech-over-noise margin.")
            if row.status == "hot":
                warnings.append(f"Channel {row.channel} ({row.name}) is close to clipping.")
        if bleed:
            warnings.append(
                "Possible microphone bleed between: "
                + ", ".join(f"{first} and {second}" for first, second in bleed)
            )

        return RoomCalibration(
            channels=tuple(rows),
            room_noise_floor_db=_round(room_floor),
            suspected_bleed_pairs=tuple(bleed),
            dead_channels=tuple(dead),
            unverified_channels=tuple(unverified),
            recommended=recommended,
            warnings=tuple(warnings),
        )


def render_calibration(calibration: RoomCalibration) -> str:
    lines = ["SPEAKERPTZ ROOM CALIBRATION", "=" * 84]
    lines.append(f"{'MIC':>3}  {'IN':>3}  {'SEAT':22} {'FLOOR':>7}  {'SPEECH':>7}  {'SNR':>6}  STATUS")
    lines.append("-" * 84)
    for row in calibration.channels:
        floor = "   --.-" if row.noise_floor_db is None else f"{row.noise_floor_db:7.1f}"
        speech = "   --.-" if row.speech_level_db is None else f"{row.speech_level_db:7.1f}"
        snr = "  --.-" if row.snr_db is None else f"{row.snr_db:6.1f}"
        lines.append(
            f"{row.channel:>3}  {row.physical_input:>3}  {row.name[:22]:22} {floor}  {speech}  {snr}  "
            f"{row.status.upper()}"
        )
    lines.append("-" * 84)
    if calibration.room_noise_floor_db is not None:
        lines.append(f"Room noise floor (median): {calibration.room_noise_floor_db:.1f} dBFS")
    if calibration.recommended:
        lines.append("")
        lines.append("SUGGESTED config/local.yaml VALUES (review before applying):")
        for key in sorted(calibration.recommended):
            lines.append(f"  audio.{key}: {calibration.recommended[key]}")
    if calibration.warnings:
        lines.append("")
        lines.append("WARNINGS:")
        for warning in calibration.warnings:
            lines.append(f"  - {warning}")
    lines.append("")
    lines.append("Only derived dB values are stored. No audio was recorded.")
    return "\n".join(lines)
