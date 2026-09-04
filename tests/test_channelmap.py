from speakerptz.audio.channelmap import normalize_channel_map, required_physical_channels


def test_default_channel_map_is_identity():
    assert normalize_channel_map(None, 4) == [1, 2, 3, 4]


def test_sparse_channel_map():
    m = normalize_channel_map([5, 6, 9, 12], 4)
    assert m == [5, 6, 9, 12]
    assert required_physical_channels(m) == 12


def test_channel_map_wrong_length_rejected():
    try:
        normalize_channel_map([1, 2], 3)
    except ValueError as exc:
        assert "entries" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_duplicate_physical_channels_rejected():
    try:
        normalize_channel_map([1, 1], 2)
    except ValueError as exc:
        assert "duplicate" in str(exc).lower()
    else:
        raise AssertionError("expected ValueError")
