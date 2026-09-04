from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CameraState(str, Enum):
    DISABLED = "disabled"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    READY = "ready"
    DEGRADED = "degraded"
    ERROR = "error"


@dataclass(frozen=True)
class CameraHealth:
    state: CameraState
    message: str = ""
    connected: bool = False
    last_error: str | None = None

    @property
    def ok(self) -> bool:
        return self.state == CameraState.READY and self.connected


@dataclass(frozen=True)
class CameraConfig:
    id: int
    name: str
    driver: str = "simulator"
    enabled: bool = True
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password_env: str | None = None
    profile_token: str | None = None
    timeout_seconds: float = 1.0

    @property
    def is_real(self) -> bool:
        return self.driver in {"visca", "onvif"}


@dataclass(frozen=True)
class CameraCommandResult:
    accepted: bool
    camera_id: int | None
    action: str
    reason: str = ""
    attempts: int = 0
