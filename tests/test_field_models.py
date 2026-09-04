from speakerptz.field.models import CheckResult, FieldPlan, SeatAssignment, StepStatus, WideShotAssignment


def test_step_status_satisfied_only_for_pass_and_human_confirmed():
    assert StepStatus.PASS.satisfied
    assert StepStatus.HUMAN_CONFIRMED.satisfied
    for status in (StepStatus.FAIL, StepStatus.WARN, StepStatus.HUMAN_REQUIRED, StepStatus.NOT_COMPLETED):
        assert not status.satisfied


def test_human_confirmed_never_equals_automated_pass():
    assert StepStatus.HUMAN_CONFIRMED is not StepStatus.PASS
    assert StepStatus.HUMAN_CONFIRMED.value != StepStatus.PASS.value


def test_check_result_ok_reflects_status():
    assert CheckResult("k", "Label", StepStatus.PASS).ok
    assert CheckResult("k", "Label", StepStatus.HUMAN_CONFIRMED).ok
    assert not CheckResult("k", "Label", StepStatus.FAIL).ok
    assert not CheckResult("k", "Label", StepStatus.HUMAN_REQUIRED).ok


def test_seat_assignment_round_trips_through_dict():
    seat = SeatAssignment(logical_channel=1, physical_input=5, name="Chair", camera=1, preset=1, enabled=True)
    restored = SeatAssignment.from_dict(seat.to_dict())
    assert restored == seat


def test_field_plan_to_dict_sorts_disabled_channels():
    plan = FieldPlan(
        seats=[SeatAssignment(1, 5, "A", 1, 1)],
        wide_shot=WideShotAssignment(1, 20),
        disabled_channels=[3, 1, 2],
    )
    data = plan.to_dict()
    assert data["disabled_channels"] == [1, 2, 3]
    assert data["wide_shot"] == {"camera": 1, "preset": 20}
