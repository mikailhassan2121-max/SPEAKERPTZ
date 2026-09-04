from __future__ import annotations


def normalize_channel_map(channel_map, logical_channels: int) -> list[int]:
    """Return a validated 1-based physical-input map for logical channels.

    Example: [5, 6, 9] means logical MIC 1 reads physical DVS input 5,
    logical MIC 2 reads physical input 6, and logical MIC 3 reads input 9.
    """
    logical_channels = int(logical_channels)
    if logical_channels < 1:
        raise ValueError("logical_channels must be >= 1")

    if channel_map is None:
        return list(range(1, logical_channels + 1))

    if not isinstance(channel_map, (list, tuple)):
        raise ValueError("audio.channel_map must be a list of 1-based physical input channels.")
    if len(channel_map) != logical_channels:
        raise ValueError(
            f"audio.channel_map has {len(channel_map)} entries but audio.channels={logical_channels}."
        )

    try:
        values = [int(v) for v in channel_map]
    except (TypeError, ValueError) as exc:
        raise ValueError("audio.channel_map must contain integers.") from exc

    if any(v < 1 for v in values):
        raise ValueError("audio.channel_map values must be >= 1.")
    if len(set(values)) != len(values):
        raise ValueError("audio.channel_map cannot contain duplicate physical channels.")
    return values


def required_physical_channels(channel_map: list[int]) -> int:
    if not channel_map:
        raise ValueError("channel_map cannot be empty")
    return max(int(v) for v in channel_map)
