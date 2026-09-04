from speakerptz.core.detector import ActiveSpeakerDetector


def make_detector(**overrides):
    values = dict(
        absolute_threshold_db=-50,
        signal_margin_db=8,
        dominance_margin_db=3,
        initial_activation_ms=0,
        switch_delay_ms=500,
        hold_time_ms=0,
        silence_timeout_ms=1000,
        calibration_seconds=0,
        confidence_min=0.55,
        now=0,
    )
    values.update(overrides)
    d = ActiveSpeakerDetector(**values)
    d.noise_floors = [-60, -60, -60]
    return d


def test_selects_speaker_by_snr():
    d = make_detector()
    event = d.update([-58, -20, -55], now=0.1)
    assert event == ("speaker", 2)


def test_rejects_noise_below_margin():
    d = make_detector()
    event = d.update([-54, -53, -55], now=0.1)
    assert event is None
    assert d.active is None


def test_crosstalk_does_not_beat_clear_source():
    d = make_detector()
    event = d.update([-34, -18, -36], now=0.1)
    assert event == ("speaker", 2)


def test_short_interjection_does_not_switch():
    d = make_detector(switch_delay_ms=700)
    assert d.update([-20, -60, -60], now=0.1) == ("speaker", 1)
    # Channel 2 becomes louder, but not for the full 700 ms switch delay.
    assert d.update([-40, -18, -60], now=0.3) is None
    assert d.update([-40, -18, -60], now=0.7) is None
    assert d.active == 1


def test_sustained_new_speaker_switches():
    d = make_detector(switch_delay_ms=500)
    assert d.update([-20, -60, -60], now=0.1) == ("speaker", 1)
    assert d.update([-40, -18, -60], now=0.3) is None
    assert d.update([-40, -18, -60], now=0.9) == ("speaker", 2)
    assert d.active == 2


def test_silence_returns_wide_event():
    d = make_detector(silence_timeout_ms=1000)
    assert d.update([-20, -60, -60], now=0.1) == ("speaker", 1)
    assert d.update([-80, -80, -80], now=0.5) is None
    assert d.update([-80, -80, -80], now=1.2) == ("silence", None)
    assert d.active is None


def test_calibration_learns_per_channel_floor():
    d = ActiveSpeakerDetector(
        calibration_seconds=1.0,
        initial_activation_ms=0,
        switch_delay_ms=0,
        hold_time_ms=0,
        now=0,
    )
    assert d.update([-61, -55, -58], now=0.2) is None
    assert d.update([-60, -56, -59], now=0.6) is None
    assert d.update([-62, -54, -57], now=1.1) is None
    assert len(d.noise_floors) == 3
    assert d.noise_floors[0] == -61.0
    assert d.noise_floors[1] == -55.0
