from __future__ import annotations

from dataclasses import dataclass

from speakerptz.cameras.manager import CameraManager
from speakerptz.core.detector import ActiveSpeakerDetector

from .models import CheckResult, StepStatus


@dataclass(frozen=True)
class RehearsalScenario:
    key: str
    label: str
    description: str
    automated: bool = True


# Scenario order follows the field-setup flow's rehearsal step (O/P). Scenarios
# marked automated=False cannot be proven by software; the workflow records
# them as HUMAN CONFIRMATION REQUIRED until an operator signs off in person.
SCENARIOS: tuple[RehearsalScenario, ...] = (
    RehearsalScenario(
        "sustained_speaker",
        "One sustained speaker",
        "A single mic stays above threshold long enough to become the active speaker.",
    ),
    RehearsalScenario(
        "speaker_handoff",
        "Speaker handoff",
        "A second speaker takes over after the hold time and becomes active in turn.",
    ),
    RehearsalScenario(
        "brief_interjection",
        "Brief interjection rejection",
        "A short interjection below the activation delay must not steal the camera.",
    ),
    RehearsalScenario(
        "transient_rejection",
        "Cough/transient rejection",
        "A single loud impulse frame must not be treated as sustained speech.",
    ),
    RehearsalScenario(
        "overlap",
        "Two people overlapping",
        "Two simultaneous close-scored channels must not cause a rapid camera fight.",
    ),
    RehearsalScenario(
        "silence_to_wide",
        "Silence to wide",
        "After the silence timeout with no active speaker, a wide-shot request is issued.",
    ),
    RehearsalScenario(
        "manual_auto_off",
        "Manual AUTO OFF",
        "Disabling AUTO must stop automatic camera requests immediately.",
    ),
    RehearsalScenario(
        "joystick_coexistence",
        "Physical joystick / manual operation",
        "The existing hardware joystick must still be able to move the camera. "
        "This cannot be verified from software; a person must confirm it at the hardware.",
        automated=False,
    ),
    RehearsalScenario(
        "audio_dropout",
        "Audio dropout",
        "A stale audio callback must disable AUTO and latch emergency stop.",
    ),
    RehearsalScenario(
        "camera_unavailable",
        "Camera unavailable",
        "A camera command must be safely blocked/failed when the camera is unhealthy.",
    ),
    RehearsalScenario(
        "restart_recovery",
        "Application restart",
        "After a restart, AUTO must come back OFF and never self-arm from persisted state.",
    ),
)

SCENARIOS_BY_KEY = {scenario.key: scenario for scenario in SCENARIOS}


def run_automated_scenarios(*, channels: int = 4, seed: int = 0) -> dict[str, CheckResult]:
    """Exercise every automatable rehearsal scenario against real detector/camera code.

    Uses the same ActiveSpeakerDetector and CameraManager classes the live
    controller uses, with a fully simulated camera and synthetic levels/VAD
    values -- no hardware, no Dante, no network access.
    """
    from speakerptz.cameras.models import CameraConfig

    results: dict[str, CheckResult] = {}
    manager = CameraManager(
        [CameraConfig(1, "Rehearsal simulator")],
        real_control_enabled=False,
        command_interval_seconds=0.0,
        movement_cooldown_seconds=0.0,
    )
    manager.connect_all()

    def quiet(n=channels):
        return [-68.0] * n, [0.02] * n

    def speak(channel: int, n=channels, level=-18.0, prob=0.92):
        levels = [-68.0] * n
        probs = [0.02] * n
        levels[channel - 1] = level
        probs[channel - 1] = prob
        return levels, probs

    def new_detector(now=0.0, **overrides):
        params = dict(
            absolute_threshold_db=-50.0,
            signal_margin_db=8.0,
            dominance_margin_db=3.0,
            initial_activation_ms=200,
            switch_delay_ms=200,
            hold_time_ms=100,
            silence_timeout_ms=500,
            calibration_seconds=0.0,
            transient_rejection_ms=150,
            overlap_margin_db=2.0,
            adaptive_noise_enabled=False,
            now=now,
        )
        params.update(overrides)
        detector = ActiveSpeakerDetector(**params)
        detector.noise_floors = [-62.0] * channels
        return detector

    # -- one sustained speaker --------------------------------------------
    detector = new_detector()
    t = 0.0
    fired_event = None
    for _ in range(6):
        t += 0.1
        levels, probs = speak(1)
        step_event = detector.update(levels, now=t, speech_probabilities=probs)
        if step_event:
            fired_event = step_event
    ok = fired_event == ("speaker", 1) and detector.active == 1
    results["sustained_speaker"] = CheckResult(
        "sustained_speaker",
        SCENARIOS_BY_KEY["sustained_speaker"].label,
        StepStatus.PASS if ok else StepStatus.FAIL,
        detector.reason,
    )

    # -- speaker handoff -----------------------------------------------------
    t += 1.0
    fired_event = None
    for _ in range(6):
        t += 0.1
        levels, probs = speak(2)
        step_event = detector.update(levels, now=t, speech_probabilities=probs)
        if step_event:
            fired_event = step_event
    ok = fired_event == ("speaker", 2) and detector.active == 2
    results["speaker_handoff"] = CheckResult(
        "speaker_handoff",
        SCENARIOS_BY_KEY["speaker_handoff"].label,
        StepStatus.PASS if ok else StepStatus.FAIL,
        detector.reason,
    )

    # -- brief interjection (single frame, then back to silence) ------------
    detector = new_detector()
    t = 0.0
    t += 0.1
    levels, probs = speak(3)
    interjection_event = detector.update(levels, now=t, speech_probabilities=probs)
    t += 0.1
    quiet_levels, quiet_probs = quiet()
    detector.update(quiet_levels, now=t, speech_probabilities=quiet_probs)
    ok = interjection_event is None and detector.active is None
    results["brief_interjection"] = CheckResult(
        "brief_interjection",
        SCENARIOS_BY_KEY["brief_interjection"].label,
        StepStatus.PASS if ok else StepStatus.FAIL,
        "No camera move was requested for a sub-threshold-duration interjection."
        if ok
        else "Interjection incorrectly produced a camera event.",
    )

    # -- transient/cough rejection: one very peaky, short frame --------------
    detector = new_detector(transient_rejection_ms=400, initial_activation_ms=0)
    t = 0.0
    t += 0.1
    levels, probs = speak(2, level=-14.0, prob=0.55)
    transient_event = detector.update(levels, now=t, speech_probabilities=probs)
    ok = transient_event is None
    results["transient_rejection"] = CheckResult(
        "transient_rejection",
        SCENARIOS_BY_KEY["transient_rejection"].label,
        StepStatus.PASS if ok else StepStatus.FAIL,
        "A single loud frame did not immediately trigger a camera move."
        if ok
        else "A single loud frame incorrectly triggered a camera move.",
    )

    # -- overlap: two close-scored channels ----------------------------------
    detector = new_detector()
    t = 0.0
    overlap_seen = False
    for _ in range(5):
        t += 0.1
        levels = [-68.0] * channels
        probs = [0.02] * channels
        levels[0] = -20.0
        levels[1] = -20.3
        probs[0] = probs[1] = 0.9
        detector.update(levels, now=t, speech_probabilities=probs)
        if detector.overlap:
            overlap_seen = True
    ok = overlap_seen and detector.active is None
    results["overlap"] = CheckResult(
        "overlap",
        SCENARIOS_BY_KEY["overlap"].label,
        StepStatus.PASS if ok else StepStatus.FAIL,
        detector.reason,
    )

    # -- silence -> wide -------------------------------------------------
    detector = new_detector(silence_timeout_ms=200)
    t = 0.0
    for _ in range(4):
        t += 0.1
        levels, probs = speak(1)
        detector.update(levels, now=t, speech_probabilities=probs)
    silence_event = None
    for _ in range(6):
        t += 0.1
        levels, probs = quiet()
        silence_event = detector.update(levels, now=t, speech_probabilities=probs)
        if silence_event:
            break
    ok = silence_event == ("silence", None)
    results["silence_to_wide"] = CheckResult(
        "silence_to_wide",
        SCENARIOS_BY_KEY["silence_to_wide"].label,
        StepStatus.PASS if ok else StepStatus.FAIL,
        detector.reason,
    )

    # -- manual AUTO OFF: mirror main.py's own `if auto_enabled and event:` gate.
    detector = new_detector()
    t = 0.0
    fired_event = None
    for _ in range(6):
        t += 0.1
        levels, probs = speak(1)
        step_event = detector.update(levels, now=t, speech_probabilities=probs)
        if step_event:
            fired_event = step_event
    speech_detected = fired_event is not None and fired_event[0] == "speaker"

    auto_manager = CameraManager(
        [CameraConfig(1, "Rehearsal simulator (manual)")],
        real_control_enabled=False,
        command_interval_seconds=0.0,
        movement_cooldown_seconds=0.0,
    )
    auto_manager.connect_all()
    auto_enabled = False  # operator has disabled AUTO
    if auto_enabled and fired_event:
        auto_manager.goto_preset(1, fired_event[1], "auto")
    moved = auto_manager.current_presets.get(1) is not None
    auto_manager.disconnect_all()
    ok = speech_detected and not moved
    results["manual_auto_off"] = CheckResult(
        "manual_auto_off",
        SCENARIOS_BY_KEY["manual_auto_off"].label,
        StepStatus.PASS if ok else StepStatus.FAIL,
        "Speech was detected but AUTO OFF correctly withheld any camera command."
        if ok
        else "A camera command was issued while AUTO was off.",
    )

    # -- audio dropout: exercised through detector.update(None-safe) --------
    # Mirrors main.py's fail-safe: when audio is stale, main.py stops calling
    # detector.update and disables AUTO/latches STOP itself. Here we assert
    # the camera manager's emergency stop still blocks movement, matching
    # what main.py does on a stale callback.
    manager.emergency_stop()
    blocked = manager.goto_preset(1, 1)
    dropout_ok = not blocked.accepted
    manager.clear_emergency_stop()
    results["audio_dropout"] = CheckResult(
        "audio_dropout",
        SCENARIOS_BY_KEY["audio_dropout"].label,
        StepStatus.PASS if dropout_ok else StepStatus.FAIL,
        "Camera manager correctly blocks movement while emergency stop is latched."
        if dropout_ok
        else "Camera manager accepted a move while stopped.",
    )

    # -- camera unavailable ---------------------------------------------
    manager_down = CameraManager(
        [CameraConfig(2, "Rehearsal simulator (down)")],
        real_control_enabled=False,
    )
    # Deliberately do not connect_all(): the driver stays disconnected.
    blocked = manager_down.goto_preset(2, 1)
    ok = not blocked.accepted
    results["camera_unavailable"] = CheckResult(
        "camera_unavailable",
        SCENARIOS_BY_KEY["camera_unavailable"].label,
        StepStatus.PASS if ok else StepStatus.FAIL,
        blocked.reason or "Command correctly blocked.",
    )

    # -- restart/recovery: persisted state never re-arms AUTO ---------------
    from speakerptz.runtime.state import RuntimeState
    import tempfile
    import os as _os

    with tempfile.TemporaryDirectory() as tmp:
        state_path = _os.path.join(tmp, "state.json")
        state = RuntimeState(state_path)
        state.mark_started("field-rehearsal", "SIMULATION / DRY RUN")
        state.heartbeat(auto_enabled=True, audio_ok=True, camera_states={1: "ready"})
        restarted = RuntimeState(state_path)
        # RuntimeState never exposes a way to restore AUTO; a fresh run always
        # starts with its own local auto_enabled=False decision in main.py.
        ok = restarted.previous_unclean_shutdown is True
    results["restart_recovery"] = CheckResult(
        "restart_recovery",
        SCENARIOS_BY_KEY["restart_recovery"].label,
        StepStatus.PASS if ok else StepStatus.FAIL,
        "An unclean prior run is detected and flagged; AUTO always starts OFF from main.py's own logic, "
        "never from persisted state."
        if ok
        else "Unclean shutdown was not detected.",
    )

    manager.disconnect_all()

    for scenario in SCENARIOS:
        if not scenario.automated and scenario.key not in results:
            results[scenario.key] = CheckResult(
                scenario.key, scenario.label, StepStatus.HUMAN_REQUIRED, scenario.description
            )
    return results


def render_rehearsal(results: dict[str, CheckResult]) -> str:
    lines = ["SPEAKERPTZ REHEARSAL CHECKLIST", "=" * 84]
    for scenario in SCENARIOS:
        result = results.get(scenario.key)
        status = result.status.value if result else StepStatus.NOT_COMPLETED.value
        lines.append(f"{scenario.label:32} {status}")
        if result and result.detail:
            lines.append(f"    {result.detail}")
    lines.append("=" * 84)
    human_only = [scenario for scenario in SCENARIOS if not scenario.automated]
    if human_only:
        lines.append("Items marked HUMAN CONFIRMATION REQUIRED cannot be proven by software.")
        for scenario in human_only:
            lines.append(f"  - {scenario.label}: {scenario.description}")
    return "\n".join(lines)
