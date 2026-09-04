from speakerptz.cameras.base import CameraCommandError, CameraDriver
from speakerptz.cameras.manager import CameraManager, camera_configs_from_data
from speakerptz.cameras.models import CameraConfig, CameraHealth, CameraState


class FakeDriver(CameraDriver):
    def __init__(self, fail_moves=0):
        self.connected = False
        self.fail_moves = fail_moves
        self.moves = []
        self.stops = 0
        self.homes = 0

    def connect(self):
        self.connected = True

    def health(self):
        state = CameraState.READY if self.connected else CameraState.DISCONNECTED
        return CameraHealth(state, connected=self.connected)

    def goto_preset(self, preset, label=""):
        if self.fail_moves:
            self.fail_moves -= 1
            raise CameraCommandError("temporary failure")
        self.moves.append((preset, label))

    def stop(self):
        self.stops += 1

    def home(self):
        self.homes += 1

    def disconnect(self):
        self.connected = False


def test_real_driver_is_not_constructed_when_global_gate_is_false():
    created = []

    def simulator_factory(cfg):
        created.append("simulator")
        return FakeDriver()

    def forbidden_real_factory(cfg):
        raise AssertionError("real driver must never be constructed")

    manager = CameraManager(
        [CameraConfig(1, "Configured real camera", driver="visca", host="192.0.2.1")],
        real_control_enabled=False,
        driver_factories={"simulator": simulator_factory, "visca": forbidden_real_factory},
    )
    assert created == ["simulator"]
    assert manager.mode_banner == "SIMULATION / DRY RUN"


def test_multiple_camera_routing():
    drivers = {1: FakeDriver(), 2: FakeDriver()}
    manager = CameraManager(
        [CameraConfig(1, "One"), CameraConfig(2, "Two")],
        driver_factories={"simulator": lambda cfg: drivers[cfg.id]},
        command_interval_seconds=0,
        movement_cooldown_seconds=0,
    )
    assert all(h.ok for h in manager.connect_all().values())
    assert manager.goto_preset(2, 7, "Seat 7").accepted
    assert drivers[1].moves == []
    assert drivers[2].moves == [(7, "Seat 7")]
    assert manager.current_presets == {2: 7}


def test_disconnected_camera_fails_safe_without_move():
    driver = FakeDriver()
    manager = CameraManager(
        [CameraConfig(1, "One")],
        driver_factories={"simulator": lambda cfg: driver},
    )
    result = manager.goto_preset(1, 2)
    assert not result.accepted
    assert "disconnected" in result.reason
    assert driver.moves == []


def test_rate_limit_and_movement_cooldown():
    now = [0.0]
    driver = FakeDriver()
    manager = CameraManager(
        [CameraConfig(1, "One")],
        driver_factories={"simulator": lambda cfg: driver},
        clock=lambda: now[0],
        command_interval_seconds=0.1,
        movement_cooldown_seconds=0.75,
    )
    manager.connect_all()
    assert manager.goto_preset(1, 1).accepted
    now[0] = 0.05
    assert "rate limit" in manager.goto_preset(1, 2).reason
    now[0] = 0.20
    assert "cooldown" in manager.goto_preset(1, 2).reason
    now[0] = 1.0
    assert manager.goto_preset(1, 2).accepted


def test_bounded_retry_recovers_once():
    driver = FakeDriver(fail_moves=1)
    manager = CameraManager(
        [CameraConfig(1, "One")],
        driver_factories={"simulator": lambda cfg: driver},
        retry_count=1,
        retry_backoff_seconds=0,
        command_interval_seconds=0,
        movement_cooldown_seconds=0,
    )
    manager.connect_all()
    result = manager.goto_preset(1, 3)
    assert result.accepted
    assert result.attempts == 2
    assert driver.moves == [(3, "")]


def test_emergency_stop_latches_and_auto_moves_stay_blocked():
    driver = FakeDriver()
    manager = CameraManager(
        [CameraConfig(1, "One")],
        driver_factories={"simulator": lambda cfg: driver},
        command_interval_seconds=0,
        movement_cooldown_seconds=0,
    )
    manager.connect_all()
    manager.emergency_stop()
    assert manager.emergency_stopped
    assert driver.stops == 1
    assert not manager.goto_preset(1, 4).accepted
    manager.clear_emergency_stop()
    assert manager.goto_preset(1, 4).accepted


def test_legacy_config_without_cameras_gets_safe_simulators():
    configs = camera_configs_from_data(
        {
            "people": [{"camera": 2}, {"camera": 1}],
            "wide_shot": {"camera": 1},
        }
    )
    assert [cfg.id for cfg in configs] == [1, 2]
    assert all(cfg.driver == "simulator" for cfg in configs)


def test_camera_health_reconnect_is_paced_and_bounded():
    now = [0.0]
    driver = FakeDriver()
    manager = CameraManager(
        [CameraConfig(1, "One")],
        driver_factories={"simulator": lambda cfg: driver},
        reconnect_interval_seconds=1.0,
        reconnect_attempt_limit=2,
        clock=lambda: now[0],
    )
    manager.connect_all()
    driver.connected = False
    manager.maintain_health()
    assert driver.connected
    driver.connected = False
    now[0] = 0.2
    manager.maintain_health()
    assert not driver.connected
    now[0] = 1.1
    manager.maintain_health()
    assert driver.connected


def test_camera_health_stops_after_bounded_failed_reconnects():
    class NeverConnects(FakeDriver):
        def __init__(self):
            super().__init__()
            self.connect_calls = 0

        def connect(self):
            self.connect_calls += 1
            raise RuntimeError("offline")

    now = [0.0]
    driver = NeverConnects()
    manager = CameraManager(
        [CameraConfig(1, "One")],
        driver_factories={"simulator": lambda cfg: driver},
        reconnect_interval_seconds=1.0,
        reconnect_attempt_limit=2,
        clock=lambda: now[0],
    )
    manager.connect_all()
    manager.maintain_health()
    now[0] = 1.1
    manager.maintain_health()
    now[0] = 5.0
    manager.maintain_health()
    assert driver.connect_calls == 3  # initial connection plus two reconnect attempts
