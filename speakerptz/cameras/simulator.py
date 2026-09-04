from .base import CameraDriver


class SimulatorCamera(CameraDriver):
    def __init__(self):
        self.last_action = "No camera request yet"

    def goto_preset(self, camera: int, preset: int, label: str = "") -> None:
        suffix = f" ({label})" if label else ""
        self.last_action = f"Camera {camera} -> Preset {preset}{suffix}"
