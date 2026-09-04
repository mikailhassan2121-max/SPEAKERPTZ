import socket
import struct

import pytest

from speakerptz.cameras.base import CameraCommandError
from speakerptz.cameras.visca import VISCA_REPLY, ViscaOverIPCamera


def reply(sequence, payload):
    return struct.pack(">HHI", VISCA_REPLY, len(payload), sequence) + payload


class FakeSocket:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []
        self.endpoint = None
        self.timeout = None
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def connect(self, endpoint):
        self.endpoint = endpoint

    def send(self, packet):
        self.sent.append(packet)
        return len(packet)

    def recv(self, size):
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def test_visca_documented_packets_and_sequences():
    fake = FakeSocket(
        [
            reply(1, bytes.fromhex("90 50 00 01 05 11 00 01 02 FF")),
            reply(2, bytes.fromhex("90 41 FF")),
            reply(3, bytes.fromhex("90 41 FF")),
            reply(4, bytes.fromhex("90 41 FF")),
        ]
    )
    camera = ViscaOverIPCamera("192.0.2.5", socket_factory=lambda family, kind: fake)
    camera.connect()
    camera.goto_preset(1)
    camera.stop()
    camera.home()

    assert fake.endpoint == ("192.0.2.5", 52381)
    assert fake.sent[0] == bytes.fromhex("01 10 00 05 00 00 00 01 81 09 00 02 FF")
    assert fake.sent[1] == bytes.fromhex("01 00 00 07 00 00 00 02 81 01 04 3F 02 00 FF")
    assert fake.sent[2] == bytes.fromhex("01 00 00 09 00 00 00 03 81 01 06 01 01 01 03 03 FF")
    assert fake.sent[3] == bytes.fromhex("01 00 00 05 00 00 00 04 81 01 06 04 FF")
    assert camera.health().ok


def test_visca_rejects_out_of_range_preset_before_send():
    fake = FakeSocket([reply(1, bytes.fromhex("90 50 00 01 FF"))])
    camera = ViscaOverIPCamera("192.0.2.5", socket_factory=lambda family, kind: fake)
    camera.connect()
    with pytest.raises(CameraCommandError, match="1-64"):
        camera.goto_preset(65)
    assert len(fake.sent) == 1


def test_visca_camera_error_is_reported():
    fake = FakeSocket(
        [
            reply(1, bytes.fromhex("90 50 00 01 FF")),
            reply(2, bytes.fromhex("90 60 02 FF")),
        ]
    )
    camera = ViscaOverIPCamera("192.0.2.5", socket_factory=lambda family, kind: fake)
    camera.connect()
    with pytest.raises(CameraCommandError, match="0x02"):
        camera.goto_preset(2)


def test_visca_build_packet_rejects_invalid_payload_length():
    with pytest.raises(ValueError):
        ViscaOverIPCamera.build_packet(b"", 1)


def test_visca_uses_udp_socket_type():
    observed = []
    fake = FakeSocket([reply(1, bytes.fromhex("90 50 00 01 FF"))])

    def factory(family, kind):
        observed.append((family, kind))
        return fake

    camera = ViscaOverIPCamera("192.0.2.5", socket_factory=factory)
    camera.connect()
    assert observed == [(socket.AF_INET, socket.SOCK_DGRAM)]
