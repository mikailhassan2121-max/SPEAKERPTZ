from speakerptz.field.models import StepStatus
from speakerptz.field.rehearsal import SCENARIOS, run_automated_scenarios, render_rehearsal


def test_all_automated_scenarios_pass_against_real_detector_and_camera_code():
    results = run_automated_scenarios()
    automated_keys = [s.key for s in SCENARIOS if s.automated]
    for key in automated_keys:
        assert key in results
        assert results[key].status is StepStatus.PASS, f"{key}: {results[key].detail}"


def test_human_only_scenario_is_never_marked_pass():
    results = run_automated_scenarios()
    human_keys = [s.key for s in SCENARIOS if not s.automated]
    assert human_keys, "expected at least one human-only scenario"
    for key in human_keys:
        assert results[key].status is StepStatus.HUMAN_REQUIRED


def test_render_rehearsal_lists_every_scenario_and_flags_human_only():
    results = run_automated_scenarios()
    text = render_rehearsal(results)
    for scenario in SCENARIOS:
        assert scenario.label in text
    assert "cannot be proven by software" in text
