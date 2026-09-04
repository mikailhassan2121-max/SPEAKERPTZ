from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .models import CheckResult, StepStatus


RECORD_SCHEMA = 1
DEFAULT_RECORD_PATH = "logs/field-setup.json"


class FieldRecord:
    """Crash-safe local journal of the school setup session.

    The journal stores derived numbers, operator signoffs, and step outcomes.
    It never stores raw audio, camera credentials, or transcripts. It lives
    under `logs/`, which is Git-ignored.
    """

    def __init__(self, path: str = DEFAULT_RECORD_PATH, wall_clock=None):
        self.path = Path(path)
        self._wall_clock = wall_clock or time.time
        self.data = self._read()

    def _read(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            raw = {}
        if not isinstance(raw, dict) or raw.get("schema") != RECORD_SCHEMA:
            raw = {}
        raw.setdefault("schema", RECORD_SCHEMA)
        raw.setdefault("site_label", "")
        raw.setdefault("operator", "")
        raw.setdefault("steps", {})
        raw.setdefault("confirmations", {})
        raw.setdefault("calibration", None)
        raw.setdefault("plan", None)
        return raw

    def save(self) -> None:
        self.data["updated_at_epoch"] = self._wall_clock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.data, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.path)

    # ---- session identity -------------------------------------------------

    def set_session(self, site_label: str = "", operator: str = "") -> None:
        if site_label:
            self.data["site_label"] = str(site_label)
        if operator:
            self.data["operator"] = str(operator)
        self.save()

    @property
    def operator(self) -> str:
        return str(self.data.get("operator", ""))

    @property
    def site_label(self) -> str:
        return str(self.data.get("site_label", ""))

    # ---- steps ------------------------------------------------------------

    def record_step(self, key: str, status: StepStatus, detail: str = "") -> None:
        self.data["steps"][str(key)] = {
            "status": StepStatus(status).value,
            "detail": str(detail),
            "at_epoch": self._wall_clock(),
            "operator": self.operator,
        }
        self.save()

    def record_result(self, result: CheckResult) -> None:
        self.record_step(result.key, result.status, result.detail)

    def clear_step(self, key: str) -> None:
        self.data["steps"].pop(str(key), None)
        self.save()

    def step_status(self, key: str) -> StepStatus | None:
        entry = self.data["steps"].get(str(key))
        if not entry:
            return None
        try:
            return StepStatus(entry.get("status"))
        except ValueError:
            return None

    def step_detail(self, key: str) -> str:
        entry = self.data["steps"].get(str(key))
        return str(entry.get("detail", "")) if entry else ""

    # ---- human-only confirmations ----------------------------------------

    def confirm(self, key: str, operator: str = "", note: str = "") -> None:
        """Record that a person physically verified something software cannot."""
        who = str(operator or self.operator).strip()
        if not who:
            raise ValueError("A human confirmation requires an operator name.")
        self.data["confirmations"][str(key)] = {
            "operator": who,
            "note": str(note),
            "at_epoch": self._wall_clock(),
        }
        self.save()

    def revoke_confirmation(self, key: str) -> None:
        self.data["confirmations"].pop(str(key), None)
        self.save()

    def confirmation(self, key: str) -> dict | None:
        entry = self.data["confirmations"].get(str(key))
        return dict(entry) if isinstance(entry, dict) else None

    def is_confirmed(self, key: str) -> bool:
        return self.confirmation(key) is not None

    # ---- derived payloads -------------------------------------------------

    def record_calibration(self, payload: dict) -> None:
        self.data["calibration"] = dict(payload)
        self.save()

    @property
    def calibration(self) -> dict | None:
        value = self.data.get("calibration")
        return dict(value) if isinstance(value, dict) else None

    def record_plan(self, payload: dict) -> None:
        self.data["plan"] = dict(payload)
        self.save()

    @property
    def plan(self) -> dict | None:
        value = self.data.get("plan")
        return dict(value) if isinstance(value, dict) else None
