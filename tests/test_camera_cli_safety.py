import pytest

from speakerptz.cameras.manager import CameraManager
from speakerptz.main import _require_explicit_real_camera_mode


def test_camera_test_is_blocked_by_default_config():
    cfg = {
        "real_control_enabled": False,
        "cameras": [{"id": 1, "name": "Board", "driver": "visca", "host": "192.0.2.1"}],
        "people": [{"camera": 1}],
        "wide_shot": {"camera": 1},
    }
    manager = CameraManager.from_config(cfg)
    with pytest.raises(SystemExit, match="real_control_enabled is false"):
        _require_explicit_real_camera_mode(cfg, manager, 1, "CAMERA TEST")
