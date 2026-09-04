from __future__ import annotations

import platform
import sys
from dataclasses import dataclass

from speakerptz.audio.devices import list_input_devices, resolve_input_device
from speakerptz.cameras.manager import CameraManager
from speakerptz.cameras.models import CameraState
from speakerptz.core.config import ConfigError, load_config

from .camera_check import check_camera_config
from .mapping import plan_from_config, validate_plan
from .models import CheckResult, StepStatus
from .rehearsal import SCENARIOS, run_automated_scenarios


# Row order mirrors the PREFERRED FIELD SETUP FLOW in the project brief.
REPORT_ROWS: tuple[tuple[str, str], ...] = (
    ("python", "Python"),
    ("configuration", "Configuration"),
    ("dante_dvs", "Dante/DVS"),
    ("mic_mapping", "Mic mapping"),
    ("mic_calibration", "Mic calibration"),
    ("camera_config", "Camera config"),
    ("camera_connectivity", "Camera connectivity"),
    ("preset_mappings", "Preset mappings"),
    ("wide_shot", "Wide shot"),
    ("dry_run_rehearsal", "Dry-run rehearsal"),
    ("manual_override", "Manual override"),
    ("physical_joystick", "Physical joystick"),
    ("real_ptz_rehearsal", "Real PTZ rehearsal"),
)


@dataclass(frozen=True)
class ReadinessReport:
    rows: tuple[CheckResult, ...]
    site_label: str = ""
    operator: str = ""

    @property
    def blocking_failures(self) -> tuple[CheckResult, ...]:
        return tuple(row for row in self.rows if row.status is StepStatus.FAIL)

    @property
    def ready_for_hardware_rehearsal(self) -> bool:
        """True once every automatable item passes and human items are confirmed.

        Real-PTZ rehearsal itself is deliberately excluded from this gate --
        it is the next physical step, not a precondition for approaching it.
        """
        gating = [row for row in self.rows if row.key != "real_ptz_rehearsal"]
        return bool(gating) and all(row.status.satisfied for row in gating)

    @property
    def field_validated(self) -> bool:
        """True only once real hardware rehearsal itself has been completed."""
        real = next((row for row in self.rows if row.key == "real_ptz_rehearsal"), None)
        return self.ready_for_hardware_rehearsal and bool(real) and real.status.satisfied

    def to_dict(self) -> dict:
        return {
            "site_label": self.site_label,
            "operator": self.operator,
            "rows": [row.to_dict() for row in self.rows],
            "ready_for_hardware_rehearsal": self.ready_for_hardware_rehearsal,
            "field_validated": self.field_validated,
        }


def _python_check() -> CheckResult:
    ok = sys.version_info >= (3, 12)
    return CheckResult(
        "python", "Python", StepStatus.PASS if ok else StepStatus.FAIL, platform.python_version()
    )


def _config_check(config_path: str):
    try:
        cfg, _routes = load_config(config_path)
    except ConfigError as exc:
        return None, CheckResult("configuration", "Configuration", StepStatus.FAIL, str(exc))
    except Exception as exc:
        # A field readiness check must degrade to a FAIL row rather than crash,
        # even for a config file that is not even syntactically valid YAML.
        return None, CheckResult("configuration", "Configuration", StepStatus.FAIL, f"{type(exc).__name__}: {exc}")
    return cfg, CheckResult("configuration", "Configuration", StepStatus.PASS, config_path)


def _dante_check(cfg: dict) -> CheckResult:
    runtime = cfg.get("runtime", {})
    if runtime.get("mode", "real") == "simulate":
        return CheckResult(
            "dante_dvs", "Dante/DVS", StepStatus.WARN, "Runtime mode is simulate; DVS was not opened."
        )
    device_name = runtime.get("device_name")
    try:
        list_input_devices()
    except Exception as exc:  # pragma: no cover - depends on host audio stack
        return CheckResult("dante_dvs", "Dante/DVS", StepStatus.FAIL, f"Could not enumerate audio devices: {exc}")
    try:
        match = resolve_input_device(
            device_index=runtime.get("device_index"),
            device_name=device_name,
            channels=1,
            hostapi_name=runtime.get("hostapi_name"),
        )
    except Exception as exc:
        return CheckResult("dante_dvs", "Dante/DVS", StepStatus.FAIL, str(exc))
    if "dante" in str(device_name or "").lower() and "dante" not in match.name.lower():
        return CheckResult(
            "dante_dvs",
            "Dante/DVS",
            StepStatus.WARN,
            f"Resolved device '{match.name}' does not contain 'Dante'; confirm this is the DVS endpoint.",
        )
    return CheckResult("dante_dvs", "Dante/DVS", StepStatus.PASS, f"{match.index} | {match.name}")


def build_readiness_report(
    config_path: str,
    *,
    field_record=None,
    include_camera_connectivity: bool = True,
    now=None,
) -> ReadinessReport:
    """Assemble the full field-readiness report from live, hardware-optional checks
    plus any operator-recorded human confirmations in `field_record`.

    Real hardware rows (Dante/DVS resolution, camera connectivity, physical
    joystick, real PTZ rehearsal) degrade to WARN/HUMAN CONFIRMATION REQUIRED
    rather than crashing when hardware or a FieldRecord is unavailable, since
    this report must also run cleanly on a development laptop.
    """
    rows: list[CheckResult] = [_python_check()]

    cfg, config_result = _config_check(config_path)
    rows.append(config_result)
    if cfg is None:
        rows.extend(
            CheckResult(key, label, StepStatus.SKIPPED, "Skipped: configuration failed to load.")
            for key, label in REPORT_ROWS
            if key not in {"python", "configuration"}
        )
        return ReadinessReport(tuple(rows))

    try:
        rows.append(_dante_check(cfg))
    except Exception as exc:  # pragma: no cover - defensive; audio stack varies
        rows.append(CheckResult("dante_dvs", "Dante/DVS", StepStatus.FAIL, str(exc)))

    plan = plan_from_config(cfg)
    camera_entries = {int(entry["id"]): entry for entry in cfg.get("cameras") or []}
    plan_results = validate_plan(plan, camera_entries)
    plan_by_key = {result.key: result for result in plan_results}

    def worst(keys, key, label):
        selected = [plan_by_key[k] for k in keys if k in plan_by_key]
        if not selected:
            return CheckResult(key, label, StepStatus.SKIPPED, "No data.")
        order = [StepStatus.FAIL, StepStatus.WARN, StepStatus.PASS]
        chosen = min(selected, key=lambda result: order.index(result.status) if result.status in order else 99)
        return CheckResult(key, label, chosen.status, chosen.detail)

    rows.append(worst(["plan_seats", "plan_physical_inputs", "plan_names"], "mic_mapping", "Mic mapping"))

    if field_record is not None and field_record.calibration:
        calibration_status = field_record.step_status("mic_calibration") or StepStatus.PASS
        rows.append(
            CheckResult(
                "mic_calibration",
                "Mic calibration",
                calibration_status,
                field_record.step_detail("mic_calibration") or "Calibration data recorded.",
            )
        )
    else:
        rows.append(
            CheckResult(
                "mic_calibration",
                "Mic calibration",
                StepStatus.NOT_COMPLETED,
                "Run calibrate_room.bat and review the suggested values.",
            )
        )

    camera_summary = check_camera_config(cfg)
    camera_status = StepStatus.PASS
    camera_detail_parts = []
    for result in camera_summary:
        if result.status is StepStatus.FAIL:
            camera_status = StepStatus.FAIL
        elif result.status is StepStatus.WARN and camera_status is StepStatus.PASS:
            camera_status = StepStatus.WARN
        camera_detail_parts.append(f"{result.label}: {result.status.value}")
    rows.append(CheckResult("camera_config", "Camera config", camera_status, "; ".join(camera_detail_parts)))

    if include_camera_connectivity and camera_entries:
        try:
            manager = CameraManager.from_config(cfg)
            health = manager.connect_all()
            manager.disconnect_all()
            unhealthy = [
                camera_id
                for camera_id, camera_health in health.items()
                if camera_health.state != CameraState.DISABLED and not camera_health.ok
            ]
            if unhealthy:
                rows.append(
                    CheckResult(
                        "camera_connectivity",
                        "Camera connectivity",
                        StepStatus.FAIL,
                        f"Unhealthy camera id(s): {unhealthy}",
                    )
                )
            else:
                effective = "REAL" if bool(cfg.get("real_control_enabled", False)) else "SIMULATED (real control off)"
                rows.append(
                    CheckResult(
                        "camera_connectivity",
                        "Camera connectivity",
                        StepStatus.PASS,
                        f"All configured cameras healthy ({effective}).",
                    )
                )
        except Exception as exc:
            rows.append(CheckResult("camera_connectivity", "Camera connectivity", StepStatus.FAIL, str(exc)))
    else:
        rows.append(
            CheckResult(
                "camera_connectivity",
                "Camera connectivity",
                StepStatus.SKIPPED if not camera_entries else StepStatus.NOT_COMPLETED,
                "No cameras configured." if not camera_entries else "Run camera_probe.bat for each camera.",
            )
        )

    rows.append(worst(["plan_presets", "plan_cameras"], "preset_mappings", "Preset mappings"))
    rows.append(worst(["plan_wide_shot"], "wide_shot", "Wide shot"))

    if field_record is not None and field_record.step_status("dry_run_rehearsal"):
        rows.append(
            CheckResult(
                "dry_run_rehearsal",
                "Dry-run rehearsal",
                field_record.step_status("dry_run_rehearsal"),
                field_record.step_detail("dry_run_rehearsal"),
            )
        )
    else:
        try:
            scenario_results = run_automated_scenarios()
            automated = [key for key, scenario in ((s.key, s) for s in SCENARIOS) if scenario.automated]
            failed = [key for key in automated if scenario_results[key].status is StepStatus.FAIL]
            status = StepStatus.FAIL if failed else StepStatus.PASS
            detail = f"{len(automated) - len(failed)}/{len(automated)} automated scenarios passed."
            rows.append(CheckResult("dry_run_rehearsal", "Dry-run rehearsal", status, detail))
        except Exception as exc:  # pragma: no cover - defensive
            rows.append(CheckResult("dry_run_rehearsal", "Dry-run rehearsal", StepStatus.FAIL, str(exc)))

    def human_row(key: str, label: str) -> CheckResult:
        if field_record is not None and field_record.is_confirmed(key):
            confirmation = field_record.confirmation(key)
            return CheckResult(
                key, label, StepStatus.HUMAN_CONFIRMED, f"Confirmed by {confirmation['operator']}."
            )
        return CheckResult(
            key, label, StepStatus.HUMAN_REQUIRED, "Requires a person to verify at the physical hardware."
        )

    rows.append(human_row("manual_override", "Manual override"))
    rows.append(human_row("physical_joystick", "Physical joystick"))

    if field_record is not None and field_record.is_confirmed("real_ptz_rehearsal"):
        confirmation = field_record.confirmation("real_ptz_rehearsal")
        rows.append(
            CheckResult(
                "real_ptz_rehearsal",
                "Real PTZ rehearsal",
                StepStatus.HUMAN_CONFIRMED,
                f"Confirmed by {confirmation['operator']}.",
            )
        )
    else:
        rows.append(
            CheckResult(
                "real_ptz_rehearsal",
                "Real PTZ rehearsal",
                StepStatus.NOT_COMPLETED,
                "Only attempt after every other row is satisfied and an operator explicitly approves it.",
            )
        )

    return ReadinessReport(tuple(rows))


def render_readiness(report: ReadinessReport) -> str:
    lines = ["SPEAKERPTZ FIELD READINESS", "=" * 60]
    for row in report.rows:
        lines.append(f"{row.label:26} {row.status.value}")
    lines.append("")
    lines.append("STATUS:")
    if report.field_validated:
        lines.append("REAL-CAMERA REHEARSAL COMPLETED")
        lines.append("STILL NOT FIELD VALIDATED until this exact sequence has been")
        lines.append("physically completed at the school with the real hardware.")
    elif report.ready_for_hardware_rehearsal:
        lines.append("READY FOR CONTROLLED HARDWARE REHEARSAL")
        lines.append("NOT FIELD VALIDATED")
    else:
        lines.append("NOT YET READY FOR CONTROLLED HARDWARE REHEARSAL")
        failing = report.blocking_failures
        if failing:
            lines.append("Blocking:")
            for row in failing:
                lines.append(f"  - {row.label}: {row.detail}")
    return "\n".join(lines)
