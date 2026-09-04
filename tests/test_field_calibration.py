import pytest

from speakerptz.field.calibration import CalibrationSession, render_calibration


def test_calibration_marks_channel_ok_with_good_snr():
    session = CalibrationSession(2, channel_map=[5, 6], names=["Chair", "Member"])
    for _ in range(10):
        session.add_noise_frame([-65.0, -64.0])
    for _ in range(10):
        session.add_speech_frame(1, [-20.0, -64.0])
    for _ in range(10):
        session.add_speech_frame(2, [-65.0, -19.0])
    result = session.result()
    statuses = {row.channel: row.status for row in result.channels}
    assert statuses == {1: "ok", 2: "ok"}
    assert result.complete
    assert not result.dead_channels
    assert not result.unverified_channels


def test_calibration_flags_dead_channel():
    session = CalibrationSession(2, channel_map=[5, 6])
    for _ in range(10):
        session.add_noise_frame([-65.0, -95.0])
    for _ in range(10):
        session.add_speech_frame(1, [-20.0, -95.0])
    # Channel 2 mic is spoken into but yields nothing back -- unsubscribed input.
    for _ in range(10):
        session.add_speech_frame(2, [-65.0, -95.0])
    result = session.result()
    row2 = next(row for row in result.channels if row.channel == 2)
    assert row2.status == "dead"
    assert 2 in result.dead_channels
    assert "disabled_channels" in result.recommended
    assert result.recommended["disabled_channels"] == [2]


def test_calibration_flags_unverified_channel_without_speech_sample():
    session = CalibrationSession(2, channel_map=[5, 6])
    for _ in range(10):
        session.add_noise_frame([-65.0, -64.0])
    for _ in range(10):
        session.add_speech_frame(1, [-20.0, -64.0])
    result = session.result()
    assert result.unverified_channels == (2,)
    assert not result.complete
    assert any("without a verified speech sample" in warning for warning in result.warnings)


def test_calibration_flags_low_snr_channel():
    session = CalibrationSession(1, channel_map=[5])
    for _ in range(10):
        session.add_noise_frame([-40.0])
    for _ in range(10):
        session.add_speech_frame(1, [-35.0])  # only 5 dB above floor
    result = session.result()
    assert result.channels[0].status == "low_snr"
    assert any("low speech-over-noise margin" in warning for warning in result.warnings)


def test_calibration_flags_hot_channel_near_clipping():
    session = CalibrationSession(1, channel_map=[5])
    for _ in range(10):
        session.add_noise_frame([-65.0])
    for _ in range(10):
        session.add_speech_frame(1, [-3.0])
    result = session.result()
    assert result.channels[0].status == "hot"
    assert result.channels[0].usable


def test_calibration_detects_bleed_between_neighboring_channels():
    session = CalibrationSession(2, channel_map=[5, 6], names=["A", "B"])
    for _ in range(10):
        session.add_noise_frame([-65.0, -65.0])
    for _ in range(10):
        # Speaking into channel 1 also registers strongly on channel 2 (bleed).
        session.add_speech_frame(1, [-20.0, -25.0])
    for _ in range(10):
        session.add_speech_frame(2, [-64.0, -19.0])
    result = session.result()
    assert (1, 2) in result.suspected_bleed_pairs
    assert "bleed_pairs" in result.recommended


def test_calibration_rejects_mismatched_frame_length():
    session = CalibrationSession(2, channel_map=[5, 6])
    with pytest.raises(ValueError):
        session.add_noise_frame([-65.0])
    with pytest.raises(ValueError):
        session.add_speech_frame(1, [-65.0, -65.0, -65.0])


def test_calibration_rejects_bad_channel_number():
    session = CalibrationSession(2, channel_map=[5, 6])
    with pytest.raises(ValueError):
        session.add_speech_frame(0, [-65.0, -65.0])
    with pytest.raises(ValueError):
        session.add_speech_frame(3, [-65.0, -65.0])


def test_calibration_requires_matching_channel_map_and_names_length():
    with pytest.raises(ValueError):
        CalibrationSession(2, channel_map=[5])
    with pytest.raises(ValueError):
        CalibrationSession(2, names=["only one"])


def test_calibration_with_no_frames_warns_and_stays_incomplete():
    session = CalibrationSession(1, channel_map=[5])
    result = session.result()
    assert not result.complete
    assert result.room_noise_floor_db is None
    assert any("No quiet-room frames" in warning for warning in result.warnings)


def test_render_calibration_includes_privacy_statement():
    session = CalibrationSession(1, channel_map=[5])
    for _ in range(5):
        session.add_noise_frame([-65.0])
    for _ in range(5):
        session.add_speech_frame(1, [-20.0])
    text = render_calibration(session.result())
    assert "No audio was recorded" in text
    assert "SEAT" in text
