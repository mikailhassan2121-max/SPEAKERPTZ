from speakerptz.cameras.manager import CameraManager
from speakerptz.cameras.models import CameraConfig
from speakerptz.field.camera_check import check_camera_config, probe_camera
from speakerptz.field.models import StepStatus


def test_check_camera_config_warns_with_no_cameras():
    results = check_camera_config({})
    assert results[0].status is StepStatus.WARN


def test_check_camera_config_passes_clean_simulator_entry_with_warn():
    cfg = {"cameras": [{"id": 1, "name": "Camera 1", "driver": "simulator", "enabled": True}]}
    results = check_camera_config(cfg)
    per_camera = next(r for r in results if r.key == "camera_1")
    assert per_camera.status is StepStatus.WARN  # simulator driver flagged as not yet real


def test_check_camera_config_rejects_plaintext_password():
    cfg = {
        "cameras": [
            {"id": 1, "name": "Camera 1", "driver": "visca", "host": "10.0.0.5", "password": "hunter2", "enabled": True}
        ]
    }
    results = check_camera_config(cfg)
    per_camera = next(r for r in results if r.key == "camera_1")
    assert per_camera.status is StepStatus.FAIL
    assert "password" in per_camera.detail.lower()


def test_check_camera_config_requires_host_for_visca():
    cfg = {"cameras": [{"id": 1, "name": "Camera 1", "driver": "visca", "enabled": True}]}
    results = check_camera_config(cfg)
    per_camera = next(r for r in results if r.key == "camera_1")
    assert per_camera.status is StepStatus.FAIL


def test_check_camera_config_requires_username_and_password_env_for_onvif():
    cfg = {"cameras": [{"id": 1, "name": "Camera 1", "driver": "onvif", "host": "10.0.0.5", "enabled": True}]}
    results = check_camera_config(cfg)
    per_camera = next(r for r in results if r.key == "camera_1")
    assert per_camera.status is StepStatus.FAIL


def test_check_camera_config_passes_valid_onvif_entry():
    cfg = {
        "cameras": [
            {
                "id": 1,
                "name": "Camera 1",
                "driver": "onvif",
                "host": "10.0.0.5",
                "username": "admin",
                "password_env": "SPEAKERPTZ_CAMERA_1_PASSWORD",
                "enabled": True,
            }
        ]
    }
    results = check_camera_config(cfg)
    per_camera = next(r for r in results if r.key == "camera_1")
    assert per_camera.status is StepStatus.PASS


def test_check_camera_config_marks_disabled_camera_as_warn():
    cfg = {"cameras": [{"id": 1, "name": "Camera 1", "driver": "visca", "host": "10.0.0.5", "enabled": False}]}
    results = check_camera_config(cfg)
    per_camera = next(r for r in results if r.key == "camera_1")
    assert per_camera.status is StepStatus.WARN


def test_probe_camera_reports_disabled_camera():
    cfg = {"cameras": [{"id": 1, "name": "Camera 1", "driver": "simulator", "enabled": False}]}
    manager = CameraManager.from_config(cfg)
    result = probe_camera(cfg, 1, manager=manager)
    assert result.status is StepStatus.WARN


def test_probe_camera_reports_healthy_simulator():
    manager = CameraManager([CameraConfig(1, "Camera 1", driver="simulator")], real_control_enabled=False)
    result = probe_camera({}, 1, manager=manager)
    assert result.status is StepStatus.PASS
