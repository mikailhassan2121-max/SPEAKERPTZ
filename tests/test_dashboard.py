import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from speakerptz.ui.dashboard import DashboardServer, DashboardState, _dashboard_html


def test_dashboard_state_snapshot_events_and_bounded_commands():
    now = [100.0]
    state = DashboardState(command_limit=1, event_limit=2, clock=lambda: now[0])
    state.update(version="0.8", auto_enabled=True, warnings=["test warning"])
    now[0] = 103.5
    state.add_event("test", "first")
    state.add_event("test", "second")
    state.add_event("test", "third")

    snapshot = state.snapshot()
    assert snapshot["version"] == "0.8"
    assert snapshot["auto_enabled"] is True
    assert snapshot["uptime_seconds"] == 3.5
    assert "control_token" not in snapshot
    assert [item["message"] for item in state.events()] == ["second", "third"]

    accepted, _ = state.enqueue("wide")
    assert accepted
    accepted, reason = state.enqueue("emergency_stop")
    assert not accepted
    assert "full" in reason
    assert state.drain_commands()[0].action == "wide"


def test_dashboard_validates_allowlisted_command_payloads():
    state = DashboardState()
    assert state.enqueue("delete_everything")[0] is False
    assert state.enqueue("manual_preset", "camera", 2)[0] is False
    assert state.enqueue("manual_preset", 1, -1)[0] is False
    assert state.enqueue("manual_preset", 2, 7)[0] is True
    command = state.drain_commands()[0]
    assert (command.action, command.camera_id, command.preset) == ("manual_preset", 2, 7)


def test_dashboard_html_contains_unmistakable_mode_banners_and_controls():
    html = _dashboard_html("test-token")
    assert "SIMULATION / DRY RUN" in html
    assert "REAL PTZ CONTROL IS ENABLED" in html
    assert "EMERGENCY STOP" in html
    assert "AUTO OFF" in html
    assert "send('auto_off')" in html
    assert "X-SpeakerPTZ-Token" in html
    assert "test-token" in html


def test_local_http_api_is_readable_but_commands_require_token():
    state = DashboardState()
    state.update(version="0.8", mode_banner="SIMULATION / DRY RUN")
    server = DashboardServer(state, "127.0.0.1", 0)
    url = server.start()
    try:
        assert server._server.daemon_threads is True
        assert server._server.block_on_close is False
        with urlopen(f"{url}/api/status", timeout=2) as response:
            status = json.load(response)
        assert status["version"] == "0.8"
        assert status["mode_banner"] == "SIMULATION / DRY RUN"

        body = json.dumps({"action": "wide"}).encode()
        unauthorized = Request(
            f"{url}/api/command",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urlopen(unauthorized, timeout=2)
        except HTTPError as exc:
            assert exc.code == 403
        else:
            raise AssertionError("command without token should be rejected")

        authorized = Request(
            f"{url}/api/command",
            data=body,
            headers={"Content-Type": "application/json", "X-SpeakerPTZ-Token": state.control_token},
            method="POST",
        )
        with urlopen(authorized, timeout=2) as response:
            result = json.load(response)
            assert response.status == 202
        assert result["accepted"] is True
        assert state.drain_commands()[0].action == "wide"
    finally:
        server.stop()
