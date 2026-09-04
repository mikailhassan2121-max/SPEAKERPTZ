from types import SimpleNamespace

import pytest

from speakerptz.cameras.base import CameraConnectionError
from speakerptz.cameras.onvif import OnvifCamera


class FakeMedia:
    def GetProfiles(self):
        return [SimpleNamespace(token="profile-1")]


class FakePTZ:
    def __init__(self):
        self.calls = []

    def GetStatus(self, request):
        self.calls.append(("GetStatus", request))
        return {}

    def GotoPreset(self, request):
        self.calls.append(("GotoPreset", request))

    def Stop(self, request):
        self.calls.append(("Stop", request))

    def GotoHomePosition(self, request):
        self.calls.append(("GotoHomePosition", request))


class FakeClient:
    def __init__(self):
        self.media = FakeMedia()
        self.ptz = FakePTZ()

    def create_media_service(self):
        return self.media

    def create_ptz_service(self):
        return self.ptz


def test_onvif_uses_profile_and_standard_ptz_operations():
    client = FakeClient()
    camera = OnvifCamera(
        "192.0.2.8",
        80,
        "operator",
        "secret",
        client_factory=lambda host, port, username, password: client,
    )
    camera.connect()
    camera.goto_preset(7)
    camera.stop()
    camera.home()
    assert camera.health().ok
    assert client.ptz.calls == [
        ("GetStatus", {"ProfileToken": "profile-1"}),
        ("GotoPreset", {"ProfileToken": "profile-1", "PresetToken": "7"}),
        ("Stop", {"ProfileToken": "profile-1", "PanTilt": True, "Zoom": True}),
        ("GotoHomePosition", {"ProfileToken": "profile-1"}),
    ]


def test_onvif_rejects_unknown_profile_token():
    client = FakeClient()
    camera = OnvifCamera(
        "192.0.2.8",
        username="operator",
        password="secret",
        profile_token="missing",
        client_factory=lambda host, port, username, password: client,
    )
    with pytest.raises(CameraConnectionError, match="not returned"):
        camera.connect()


def test_onvif_error_does_not_repeat_password():
    def broken(*args):
        raise RuntimeError("login secret failed")

    camera = OnvifCamera(
        "192.0.2.8",
        username="operator",
        password="secret",
        client_factory=broken,
    )
    with pytest.raises(CameraConnectionError) as exc_info:
        camera.connect()
    assert "secret" not in str(exc_info.value)
    assert "***" in str(exc_info.value)
