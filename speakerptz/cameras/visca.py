from __future__ import annotations

import socket
import struct
import threading

from .base import CameraCommandError, CameraConnectionError, CameraDriver
from .models import CameraHealth, CameraState


VISCA_COMMAND = 0x0100
VISCA_INQUIRY = 0x0110
VISCA_REPLY = 0x0111
DEFAULT_VISCA_PORT = 52381


class ViscaOverIPCamera(CameraDriver):
    """Sony-style VISCA over IP using the documented UDP framing."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_VISCA_PORT,
        timeout_seconds: float = 1.0,
        socket_factory=None,
    ):
        self.host = str(host)
        self.port = int(port)
        self.timeout_seconds = float(timeout_seconds)
        self._socket_factory = socket_factory or socket.socket
        self._socket = None
        self._sequence = 1
        self._lock = threading.Lock()
        self._connected = False
        self._last_error: str | None = None

    @staticmethod
    def build_packet(payload: bytes, sequence: int, payload_type: int = VISCA_COMMAND) -> bytes:
        if not 1 <= len(payload) <= 16:
            raise ValueError("VISCA payload must contain 1 to 16 bytes.")
        return struct.pack(">HHI", int(payload_type), len(payload), int(sequence) & 0xFFFFFFFF) + payload

    def _next_sequence(self) -> int:
        value = self._sequence
        self._sequence = (self._sequence + 1) & 0xFFFFFFFF
        return value

    def _parse_reply(self, packet: bytes, expected_sequence: int) -> bytes:
        if len(packet) < 9:
            raise CameraCommandError("VISCA reply was shorter than its 8-byte header plus payload.")
        payload_type, payload_length, sequence = struct.unpack(">HHI", packet[:8])
        payload = packet[8:]
        if payload_type != VISCA_REPLY:
            raise CameraCommandError(f"Unexpected VISCA reply type 0x{payload_type:04X}.")
        if payload_length != len(payload):
            raise CameraCommandError("VISCA reply payload length did not match its header.")
        if sequence != expected_sequence:
            raise CameraCommandError("VISCA reply sequence did not match the command.")
        if len(payload) < 2 or payload[0] != 0x90:
            raise CameraCommandError("VISCA reply payload was not a camera response.")
        response_class = payload[1] & 0xF0
        if response_class == 0x60:
            code = payload[2] if len(payload) > 2 else 0
            raise CameraCommandError(f"VISCA camera returned error 0x{code:02X}.")
        if response_class not in {0x40, 0x50}:
            raise CameraCommandError(f"Unexpected VISCA response class 0x{response_class:02X}.")
        return payload

    def _exchange(self, payload: bytes, payload_type: int) -> bytes:
        if self._socket is None:
            raise CameraConnectionError("VISCA socket is not connected.")
        sequence = self._next_sequence()
        packet = self.build_packet(payload, sequence, payload_type)
        try:
            self._socket.send(packet)
            reply = self._socket.recv(64)
        except (OSError, TimeoutError) as exc:
            self._last_error = str(exc)
            self._connected = False
            raise CameraConnectionError(f"VISCA communication with {self.host}:{self.port} failed: {exc}") from exc
        return self._parse_reply(reply, sequence)

    def connect(self) -> None:
        if self._connected:
            return
        sock = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.timeout_seconds)
        try:
            sock.connect((self.host, self.port))
            self._socket = sock
            # CAM_VersionInq is read-only and confirms that a VISCA device replies.
            self._exchange(bytes.fromhex("81 09 00 02 FF"), VISCA_INQUIRY)
        except Exception as exc:
            try:
                sock.close()
            except Exception:
                pass
            self._socket = None
            self._connected = False
            self._last_error = str(exc)
            if isinstance(exc, CameraConnectionError):
                raise
            raise CameraConnectionError(f"Could not connect to VISCA camera {self.host}:{self.port}: {exc}") from exc
        self._connected = True
        self._last_error = None

    def health(self) -> CameraHealth:
        if self._connected:
            return CameraHealth(CameraState.READY, f"VISCA UDP {self.host}:{self.port}", connected=True)
        state = CameraState.ERROR if self._last_error else CameraState.DISCONNECTED
        return CameraHealth(state, "VISCA camera is not connected", last_error=self._last_error)

    def goto_preset(self, preset: int, label: str = "") -> None:
        preset_number = int(preset)
        if not 1 <= preset_number <= 64:
            raise CameraCommandError("VISCA preset must be in the documented 1-64 range.")
        # Sony command list uses pp = displayed preset number - 1.
        payload = bytes((0x81, 0x01, 0x04, 0x3F, 0x02, preset_number - 1, 0xFF))
        with self._lock:
            self._exchange(payload, VISCA_COMMAND)

    def stop(self) -> None:
        # Pan/tilt stop with the lowest valid pan/tilt speed values.
        payload = bytes.fromhex("81 01 06 01 01 01 03 03 FF")
        with self._lock:
            self._exchange(payload, VISCA_COMMAND)

    def home(self) -> None:
        with self._lock:
            self._exchange(bytes.fromhex("81 01 06 04 FF"), VISCA_COMMAND)

    def disconnect(self) -> None:
        sock, self._socket = self._socket, None
        self._connected = False
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
