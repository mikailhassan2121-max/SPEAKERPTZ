from __future__ import annotations

from .base import CameraDriver, CameraConnectionError
from .models import CameraHealth, CameraState


class SimulatorCamera(CameraDriver):
    def __init__(self, camera_id: int = 1, name: str = "Simulated camera"):
        self.camera_id = int(camera_id)
        self.name = name
        self.connected = False
        self.last_action = "No camera request yet"
        self.history: list[str] = []

    def connect(self) -> None:
        self.connected = True
        self.last_action = f"Camera {self.camera_id} simulator connected"

    def health(self) -> CameraHealth:
        if self.connected:
            return CameraHealth(CameraState.READY, "simulation", connected=True)
        return CameraHealth(CameraState.DISCONNECTED, "simulator not connected")

    def goto_preset(self, preset: int, label: str = "") -> None:
        if not self.connected:
            raise CameraConnectionError("Simulator camera is not connected.")
        suffix = f" ({label})" if label else ""
        self.last_action = f"Camera {self.camera_id} -> Preset {int(preset)}{suffix}"
        self.history.append(self.last_action)

    def stop(self) -> None:
        self.last_action = f"Camera {self.camera_id} -> STOP"
        self.history.append(self.last_action)

    def home(self) -> None:
        self.last_action = f"Camera {self.camera_id} -> HOME"
        self.history.append(self.last_action)

    def disconnect(self) -> None:
        self.connected = False
