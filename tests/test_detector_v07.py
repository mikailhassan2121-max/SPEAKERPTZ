from speakerptz.core.detector import ActiveSpeakerDetector


def detector(**overrides):
    values = dict(
        absolute_threshold_db=-50,
        signal_margin_db=8,
        initial_activation_ms=0,
        switch_delay_ms=400,
        hold_time_ms=0,
        silence_timeout_ms=1000,
        calibration_seconds=0,
        confidence_min=0.55,
        transient_rejection_ms=180,
        overlap_margin_db=2,
        now=0,
    )
    values.update(overrides)
    result = ActiveSpeakerDetector(**values)
    result.noise_floors = [-60.0, -60.0, -60.0]
    return result


def test_loud_non_speech_does_not_select_a_camera_target():
    d = detector()
    assert d.update([-18, -70, -70], now=0.1, speech_probabilities=[0.12, 0.0, 0.0]) is None
    assert d.active is None
    assert d.reason == "no channel contains confident speech"


def test_sustained_vad_activity_passes_transient_rejection():
    d = detector()
    assert d.update([-20, -70, -70], now=0.10, speech_probabilities=[0.92, 0.0, 0.0]) is None
    assert "confirming speech" in d.reason
    assert d.update([-21, -70, -70], now=0.35, speech_probabilities=[0.90, 0.0, 0.0]) == ("speaker", 1)


def test_short_cough_like_burst_does_not_activate():
    d = detector()
    assert d.update([-15, -70, -70], now=0.10, speech_probabilities=[0.95, 0.0, 0.0]) is None
    assert d.update([-70, -70, -70], now=0.20, speech_probabilities=[0.0, 0.0, 0.0]) is None
    assert d.active is None


def test_configured_neighbor_bleed_is_rejected():
    d = detector(transient_rejection_ms=0, bleed_pairs=[[1, 2]], bleed_rejection_db=6)
    event = d.update([-18, -32, -70], now=0.1, speech_probabilities=[0.92, 0.82, 0.0])
    assert event == ("speaker", 1)
    assert d.eligible == [True, False, False]


def test_ambiguous_overlap_prefers_no_initial_move():
    d = detector(transient_rejection_ms=0)
    assert d.update([-20, -20.5, -70], now=0.1, speech_probabilities=[0.9, 0.9, 0.0]) is None
    assert d.active is None
    assert d.overlap
    assert "no camera move" in d.reason


def test_overlap_holds_current_speaker():
    d = detector(transient_rejection_ms=0)
    assert d.update([-18, -35, -70], now=0.1, speech_probabilities=[0.9, 0.7, 0.0]) == ("speaker", 1)
    assert d.update([-20, -20.5, -70], now=0.5, speech_probabilities=[0.9, 0.9, 0.0]) is None
    assert d.active == 1
    assert d.overlap
    assert "holding mic 1" in d.reason


def test_disabled_channel_is_never_selected():
    d = detector(transient_rejection_ms=0, disabled_channels=[2])
    assert d.update([-70, -12, -70], now=0.1, speech_probabilities=[0.0, 0.99, 0.0]) is None
    assert d.active is None
    assert d.eligible == [False, False, False]


def test_adaptive_floor_tracks_quiet_change_within_bounds():
    d = detector(adaptive_noise_alpha=0.5, noise_floor_min_db=-80, noise_floor_max_db=-40)
    d.noise_floors = [-70.0, -70.0, -70.0]
    d.update([-60, -70, -70], now=0.1, speech_probabilities=[0.0, 0.0, 0.0])
    assert d.noise_floors[0] == -65.0
    for index in range(20):
        d.update([-20, -70, -70], now=0.2 + index / 10, speech_probabilities=[0.0, 0.0, 0.0])
    assert d.noise_floors[0] <= -40.0


def test_vad_channel_mismatch_fails_safe():
    d = detector(transient_rejection_ms=0)
    assert d.update([-20, -70, -70], now=0.1, speech_probabilities=[0.9]) is None
    assert d.active is None
    assert "mismatch" in d.reason

