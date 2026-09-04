import numpy as np

from speakerptz.audio.vad import AudioObservation, VoiceActivityAnalyzer


def sine_frame(frequency=220.0, amplitude=0.1, sample_rate=48000, samples=1024):
    t = np.arange(samples, dtype=np.float64) / sample_rate
    return (amplitude * np.sin(2.0 * np.pi * frequency * t))[:, np.newaxis]


def test_sustained_speech_band_signal_reaches_confident_vad():
    vad = VoiceActivityAnalyzer(48000, 1)
    observation = None
    for _ in range(3):
        observation = vad.analyze(sine_frame())
    assert isinstance(observation, AudioObservation)
    assert observation.levels_db[0] > -30.0
    assert observation.speech_probabilities[0] > 0.75


def test_broadband_noise_stays_below_default_speech_threshold():
    vad = VoiceActivityAnalyzer(48000, 1)
    noise = np.random.default_rng(7).normal(0.0, 0.1, (1024, 1))
    observation = None
    for _ in range(6):
        observation = vad.analyze(noise)
    assert observation.speech_probabilities[0] < 0.55


def test_single_impulse_is_rejected_as_a_transient():
    vad = VoiceActivityAnalyzer(48000, 1)
    impulse = np.zeros((1024, 1), dtype=np.float64)
    impulse[512, 0] = 1.0
    observation = vad.analyze(impulse)
    assert observation.levels_db[0] > -40.0
    assert observation.speech_probabilities[0] < 0.20


def test_vad_is_channel_independent_and_validates_shape():
    vad = VoiceActivityAnalyzer(48000, 2)
    quiet = np.zeros((1024, 1), dtype=np.float64)
    frame = np.concatenate((sine_frame(), quiet), axis=1)
    for _ in range(3):
        observation = vad.analyze(frame)
    assert observation.speech_probabilities[0] > 0.75
    assert observation.speech_probabilities[1] == 0.0

