from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable

from .base import CameraConnectionError, CameraDriver
from .models import CameraCommandResult, CameraConfig, CameraHealth, CameraState
from .onvif import OnvifCamera
from .simulator import SimulatorCamera
from .visca import DEFAULT_VISCA_PORT, ViscaOverIPCamera


DriverFactory = Callable[[CameraConfig], CameraDriver]


def camera_configs_from_data(data: dict) -> list[CameraConfig]:
    raw = data.get("cameras")
    if not raw:
        ids = {int(p["camera"]) for p in data.get("people", [])}
        if data.get("wide_shot"):
            ids.add(int(data["wide_shot"]["camera"]))
        return [CameraConfig(id=camera_id, name=f"Camera {camera_id}") for camera_id in sorted(ids)]

    configs = []
    for entry in raw:
        driver = str(entry.get("driver", "simulator")).strip().lower()
        default_port = DEFAULT_VISCA_PORT if driver == "visca" else (80 if driver == "onvif" else None)
        configs.append(
            CameraConfig(
                id=int(entry["id"]),
                name=str(entry.get("name") or f"Camera {entry['id']}"),
                driver=driver,
                enabled=bool(entry.get("enabled", True)),
                host=str(entry["host"]).strip() if entry.get("host") is not None else None,
                port=int(entry.get("port") or default_port) if (entry.get("port") or default_port) else None,
                username=str(entry.get("username") or "") or None,
                password_env=str(entry.get("password_env") or "") or None,
                profile_token=str(entry.get("profile_token")) if entry.get("profile_token") is not None else None,
                timeout_seconds=float(entry.get("timeout_seconds", 1.0)),
            )
        )
    return configs


class CameraManager:
    """Routes high-level requests to isolated camera drivers with safety gates."""

    def __init__(
        self,
        configs: list[CameraConfig],
        *,
        real_control_enabled: bool = False,
        command_interval_seconds: float = 0.10,
        movement_cooldown_seconds: float = 0.75,
        retry_count: int = 1,
        retry_backoff_seconds: float = 0.10,
        reconnect_interval_seconds: float = 2.0,
        reconnect_attempt_limit: int = 3,
        logger=None,
        clock=None,
        sleeper=None,
        driver_factories: dict[str, DriverFactory] | None = None,
    ):
        self.configs = {cfg.id: cfg for cfg in configs}
        self.real_control_enabled = bool(real_control_enabled)
        self.command_interval_seconds = max(0.0, float(command_interval_seconds))
        self.movement_cooldown_seconds = max(0.0, float(movement_cooldown_seconds))
        self.retry_count = max(0, min(3, int(retry_count)))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self.reconnect_interval_seconds = max(0.1, float(reconnect_interval_seconds))
        self.reconnect_attempt_limit = max(0, min(10, int(reconnect_attempt_limit)))
        self.logger = logger
        self._clock = clock or time.monotonic
        self._sleep = sleeper or time.sleep
        self._factories = driver_factories or {}
        self._drivers: dict[int, CameraDriver] = {}
        self._last_command_at: dict[int, float] = {}
        self._last_global_command_at: float | None = None
        self._last_reconnect_at: dict[int, float] = {}
        self._reconnect_attempts: dict[int, int] = {}
        self._lock = threading.RLock()
        self.emergency_stopped = False
        self.last_action = "No camera request yet"
        self._current_presets: dict[int, int] = {}

        for cfg in configs:
            if cfg.enabled:
                self._drivers[cfg.id] = self._make_driver(cfg)

    @classmethod
    def from_config(cls, data: dict, **overrides):
        control = data.get("camera_control", {})
        kwargs = dict(
            real_control_enabled=bool(data.get("real_control_enabled", False)),
            command_interval_seconds=float(control.get("command_interval_seconds", 0.10)),
            movement_cooldown_seconds=float(control.get("movement_cooldown_seconds", 0.75)),
            retry_count=int(control.get("retry_count", 1)),
            retry_backoff_seconds=float(control.get("retry_backoff_seconds", 0.10)),
            reconnect_interval_seconds=float(control.get("reconnect_interval_seconds", 2.0)),
            reconnect_attempt_limit=int(control.get("reconnect_attempt_limit", 3)),
        )
        kwargs.update(overrides)
        return cls(camera_configs_from_data(data), **kwargs)

    @property
    def mode_banner(self) -> str:
        return "REAL PTZ CONTROL ENABLED" if self.real_control_enabled else "SIMULATION / DRY RUN"

    @property
    def current_presets(self) -> dict[int, int]:
        with self._lock:
            return dict(self._current_presets)

    def _make_driver(self, cfg: CameraConfig) -> CameraDriver:
        # A real driver is never even constructed until the global opt-in is true.
        effective = cfg.driver if self.real_control_enabled else "simulator"
        if effective in self._factories:
            return self._factories[effective](cfg)
        if effective == "simulator":
            return SimulatorCamera(cfg.id, cfg.name)
        if effective == "visca":
            return ViscaOverIPCamera(cfg.host or "", cfg.port or DEFAULT_VISCA_PORT, cfg.timeout_seconds)
        if effective == "onvif":
            password = os.environ.get(cfg.password_env or "", "")
            if cfg.password_env and not password:
                raise CameraConnectionError(
                    f"Camera {cfg.id} requires environment variable {cfg.password_env}; no password was loaded."
                )
            return OnvifCamera(
                cfg.host or "",
                cfg.port or 80,
                cfg.username or "",
                password,
                cfg.profile_token,
                cfg.timeout_seconds,
            )
        raise ValueError(f"Unsupported camera driver: {cfg.driver}")

    def _log(self, event: str, **fields) -> None:
        if self.logger is None:
            return
        from speakerptz.runtime.logging import event as log_event

        log_event(self.logger, event, **fields)

    def connect(self, camera_id: int) -> CameraHealth:
        camera_id = int(camera_id)
        cfg = self.configs.get(camera_id)
        driver = self._drivers.get(camera_id)
        if cfg is None:
            return CameraHealth(CameraState.ERROR, f"Camera {camera_id} is not configured.")
        if not cfg.enabled or driver is None:
            return CameraHealth(CameraState.DISABLED, f"Camera {camera_id} is disabled.")
        try:
            driver.connect()
            health = driver.health()
            self._log(
                "camera_connected",
                camera_id=camera_id,
                configured_driver=cfg.driver,
                effective_driver=type(driver).__name__,
                real_control=self.real_control_enabled,
            )
            return health
        except Exception as exc:
            self._log("camera_connect_failed", camera_id=camera_id, error=str(exc))
            return CameraHealth(CameraState.ERROR, "Connection failed", last_error=str(exc))

    def connect_all(self) -> dict[int, CameraHealth]:
        return {camera_id: self.connect(camera_id) for camera_id in sorted(self.configs)}

    def health(self, camera_id: int) -> CameraHealth:
        cfg = self.configs.get(int(camera_id))
        driver = self._drivers.get(int(camera_id))
        if cfg is None:
            return CameraHealth(CameraState.ERROR, f"Camera {camera_id} is not configured.")
        if not cfg.enabled or driver is None:
            return CameraHealth(CameraState.DISABLED, f"Camera {camera_id} is disabled.")
        return driver.health()

    def health_all(self) -> dict[int, CameraHealth]:
        return {camera_id: self.health(camera_id) for camera_id in sorted(self.configs)}

    def maintain_health(self) -> dict[int, CameraHealth]:
        """Perform bounded, paced reconnect attempts for unhealthy cameras."""
        now = self._clock()
        results = self.health_all()
        for camera_id, health in list(results.items()):
            if health.state == CameraState.DISABLED:
                continue
            if health.ok:
                self._reconnect_attempts[camera_id] = 0
                continue
            attempts = self._reconnect_attempts.get(camera_id, 0)
            last = self._last_reconnect_at.get(camera_id)
            if attempts >= self.reconnect_attempt_limit:
                continue
            if last is not None and now - last < self.reconnect_interval_seconds:
                continue
            self._last_reconnect_at[camera_id] = now
            self._reconnect_attempts[camera_id] = attempts + 1
            driver = self._drivers.get(camera_id)
            if driver is not None:
                try:
                    driver.disconnect()
                except Exception:
                    pass
            results[camera_id] = self.connect(camera_id)
            self._log(
                "camera_reconnect",
                camera_id=camera_id,
                attempt=self._reconnect_attempts[camera_id],
                success=results[camera_id].ok,
            )
            if results[camera_id].ok:
                self._reconnect_attempts[camera_id] = 0
        return results

    def _run_with_retries(self, camera_id: int, action: str, operation) -> CameraCommandResult:
        attempts = 0
        last_error = ""
        for attempt in range(self.retry_count + 1):
            attempts += 1
            try:
                operation()
                self._log("camera_command", camera_id=camera_id, action=action, attempts=attempts)
                return CameraCommandResult(True, camera_id, action, attempts=attempts)
            except Exception as exc:
                last_error = str(exc)
                self._log(
                    "camera_command_failed",
                    camera_id=camera_id,
                    action=action,
                    attempt=attempts,
                    error=last_error,
                )
                if attempt >= self.retry_count:
                    break
                driver = self._drivers[camera_id]
                if not driver.health().ok:
                    try:
                        driver.disconnect()
                        driver.connect()
                    except Exception as reconnect_exc:
                        last_error = str(reconnect_exc)
                if self.retry_backoff_seconds:
                    self._sleep(self.retry_backoff_seconds)
        return CameraCommandResult(False, camera_id, action, last_error, attempts)

    def goto_preset(self, camera_id: int, preset: int, label: str = "", *, force: bool = False) -> CameraCommandResult:
        camera_id = int(camera_id)
        preset = int(preset)
        action = f"preset {preset}" + (f" ({label})" if label else "")
        with self._lock:
            if self.emergency_stopped:
                return CameraCommandResult(False, camera_id, action, "Emergency stop is latched.")
            driver = self._drivers.get(camera_id)
            cfg = self.configs.get(camera_id)
            if cfg is None:
                return CameraCommandResult(False, camera_id, action, "Camera is not configured.")
            if not cfg.enabled or driver is None:
                return CameraCommandResult(False, camera_id, action, "Camera is disabled.")
            if not driver.health().ok:
                return CameraCommandResult(False, camera_id, action, "Camera is disconnected; no move sent.")

            now = self._clock()
            if not force and self._last_global_command_at is not None:
                if now - self._last_global_command_at < self.command_interval_seconds:
                    return CameraCommandResult(False, camera_id, action, "Command rate limit is active.")
            if not force and camera_id in self._last_command_at:
                if now - self._last_command_at[camera_id] < self.movement_cooldown_seconds:
                    return CameraCommandResult(False, camera_id, action, "Camera movement cooldown is active.")

            result = self._run_with_retries(camera_id, action, lambda: driver.goto_preset(preset, label))
            if result.accepted:
                self._last_global_command_at = now
                self._last_command_at[camera_id] = now
                self._current_presets[camera_id] = preset
                self.last_action = f"Camera {camera_id} -> Preset {preset}" + (f" ({label})" if label else "")
            else:
                self.last_action = f"Camera {camera_id} command failed: {result.reason}"
            return result

    def stop(self, camera_id: int) -> CameraCommandResult:
        camera_id = int(camera_id)
        driver = self._drivers.get(camera_id)
        if driver is None or not driver.health().ok:
            return CameraCommandResult(False, camera_id, "stop", "Camera is disabled or disconnected.")
        result = self._run_with_retries(camera_id, "stop", driver.stop)
        if result.accepted:
            self.last_action = f"Camera {camera_id} -> STOP"
        return result

    def home(self, camera_id: int) -> CameraCommandResult:
        camera_id = int(camera_id)
        driver = self._drivers.get(camera_id)
        if self.emergency_stopped:
            return CameraCommandResult(False, camera_id, "home", "Emergency stop is latched.")
        if driver is None or not driver.health().ok:
            return CameraCommandResult(False, camera_id, "home", "Camera is disabled or disconnected.")
        result = self._run_with_retries(camera_id, "home", driver.home)
        if result.accepted:
            self.last_action = f"Camera {camera_id} -> HOME"
        return result

    def emergency_stop(self) -> dict[int, CameraCommandResult]:
        with self._lock:
            self.emergency_stopped = True
            results = {camera_id: self.stop(camera_id) for camera_id in sorted(self._drivers)}
            self.last_action = "EMERGENCY STOP LATCHED"
            self._log("camera_emergency_stop", camera_ids=sorted(self._drivers))
            return results

    def clear_emergency_stop(self) -> None:
        with self._lock:
            self.emergency_stopped = False
            self.last_action = "Emergency stop cleared; AUTO remains off"
            self._log("camera_emergency_stop_cleared")

    def disconnect_all(self) -> None:
        for camera_id, driver in self._drivers.items():
            try:
                driver.disconnect()
            except Exception as exc:
                self._log("camera_disconnect_failed", camera_id=camera_id, error=str(exc))
