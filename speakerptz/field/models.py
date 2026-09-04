from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class StepStatus(str, Enum):
    """Field-check outcome.

    A human-only item can never become an automated PASS. It is reported as
    HUMAN_REQUIRED until an operator records a signoff, and then as
    HUMAN_CONFIRMED, which stays visibly distinct from an automated PASS.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    HUMAN_REQUIRED = "HUMAN CONFIRMATION REQUIRED"
    HUMAN_CONFIRMED = "HUMAN CONFIRMED"
    NOT_COMPLETED = "NOT YET COMPLETED"
    SKIPPED = "SKIPPED"

    @property
    def is_failure(self) -> bool:
        return self is StepStatus.FAIL

    @property
    def is_automated_pass(self) -> bool:
        return self is StepStatus.PASS

    @property
    def satisfied(self) -> bool:
        """True when this item no longer blocks a controlled hardware rehearsal."""
        return self in {StepStatus.PASS, StepStatus.HUMAN_CONFIRMED}


@dataclass(frozen=True)
class CheckResult:
    key: str
    label: str
    status: StepStatus
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status.satisfied

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class SeatAssignment:
    """One board seat: logical mic -> physical DVS input -> camera preset."""

    logical_channel: int
    physical_input: int
    name: str
    camera: int
    preset: int
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "logical_channel": int(self.logical_channel),
            "physical_input": int(self.physical_input),
            "name": str(self.name),
            "camera": int(self.camera),
            "preset": int(self.preset),
            "enabled": bool(self.enabled),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SeatAssignment":
        return cls(
            logical_channel=int(data["logical_channel"]),
            physical_input=int(data["physical_input"]),
            name=str(data["name"]),
            camera=int(data["camera"]),
            preset=int(data["preset"]),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass(frozen=True)
class WideShotAssignment:
    camera: int
    preset: int

    def to_dict(self) -> dict:
        return {"camera": int(self.camera), "preset": int(self.preset)}


@dataclass
class FieldPlan:
    """Everything the guided workflow collects before it writes configuration."""

    seats: list[SeatAssignment] = field(default_factory=list)
    wide_shot: WideShotAssignment | None = None
    disabled_channels: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "seats": [seat.to_dict() for seat in self.seats],
            "wide_shot": self.wide_shot.to_dict() if self.wide_shot else None,
            "disabled_channels": sorted(int(value) for value in self.disabled_channels),
        }
