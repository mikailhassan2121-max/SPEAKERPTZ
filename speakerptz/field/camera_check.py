from __future__ import annotations

from speakerptz.cameras.manager import CameraManager
from speakerptz.cameras.models import CameraState

from .models import CheckResult, StepStatus


def check_camera_config(cfg: dict) -> list[CheckResult]:
    """Bounded, read-only sanity checks on cameras[] before any connectivity test.

    Does not open a socket. Flags anything that would make camera_probe.bat or
    camera_test.bat fail in a confusing way, and flags credentials that were
    typed directly into YAML instead of an environment variable.
    """
    results: list[CheckResult] = []
    cameras = cfg.get("cameras") or []
    if not cameras:
        results.append(
            CheckResult(
                "camera_entries",
                "Camera entries",
                StepStatus.WARN,
                "No cameras[] are configured yet; add at least one before preset mapping.",
            )
        )
        return results

    results.append(
        CheckResult("camera_entries", "Camera entries", StepStatus.PASS, f"{len(cameras)} camera(s) configured.")
    )

    for entry in cameras:
        camera_id = entry.get("id")
        label = f"Camera {camera_id}"
        driver = str(entry.get("driver", "simulator")).lower()
        enabled = bool(entry.get("enabled", True))
        if not enabled:
            results.append(CheckResult(f"camera_{camera_id}", label, StepStatus.WARN, "Camera is disabled."))
            continue
        if driver == "simulator":
            results.append(
                CheckResult(
                    f"camera_{camera_id}",
                    label,
                    StepStatus.WARN,
                    "Still using the simulator driver; set driver: visca or onvif once the model is confirmed.",
                )
            )
            continue
        if "password" in entry:
            results.append(
                CheckResult(
                    f"camera_{camera_id}",
                    label,
                    StepStatus.FAIL,
                    "Plaintext 'password' field found; use password_env and set the value as a Windows "
                    "environment variable instead.",
                )
            )
            continue
        if not str(entry.get("host") or "").strip():
            results.append(
                CheckResult(f"camera_{camera_id}", label, StepStatus.FAIL, f"Driver {driver} requires host.")
            )
            continue
        if driver == "onvif":
            if not str(entry.get("username") or "").strip():
                results.append(
                    CheckResult(f"camera_{camera_id}", label, StepStatus.FAIL, "ONVIF driver requires username.")
                )
                continue
            if not str(entry.get("password_env") or "").strip():
                results.append(
                    CheckResult(
                        f"camera_{camera_id}", label, StepStatus.FAIL, "ONVIF driver requires password_env."
                    )
                )
                continue
        results.append(
            CheckResult(
                f"camera_{camera_id}",
                label,
                StepStatus.PASS,
                f"driver={driver} host={entry.get('host')} port={entry.get('port') or 'default'}",
            )
        )
    return results


def probe_camera(cfg: dict, camera_id: int, *, manager: CameraManager | None = None) -> CheckResult:
    """Run the existing bounded single-camera connectivity check.

    Reuses CameraManager exactly as camera_probe.bat does; this wraps that
    call with a CheckResult so it can be folded into a readiness report. Real
    control must already be enabled in cfg for this to touch real hardware --
    otherwise CameraManager transparently substitutes the simulator driver.
    """
    manager = manager or CameraManager.from_config(cfg)
    health = manager.connect(int(camera_id))
    manager.disconnect_all()
    if health.state == CameraState.DISABLED:
        return CheckResult(
            f"camera_probe_{camera_id}", f"Camera {camera_id} connectivity", StepStatus.WARN, "Camera is disabled."
        )
    status = StepStatus.PASS if health.ok else StepStatus.FAIL
    detail = health.message or health.last_error or health.state.value
    return CheckResult(f"camera_probe_{camera_id}", f"Camera {camera_id} connectivity", status, detail)
