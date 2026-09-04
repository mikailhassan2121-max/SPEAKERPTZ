from __future__ import annotations

from .base import CameraCommandError, CameraConnectionError, CameraDriver
from .models import CameraHealth, CameraState


class OnvifCamera(CameraDriver):
    """ONVIF PTZ preset driver backed by python-onvif-zeep."""

    def __init__(
        self,
        host: str,
        port: int = 80,
        username: str = "",
        password: str = "",
        profile_token: str | None = None,
        timeout_seconds: float = 2.0,
        client_factory=None,
    ):
        self.host = str(host)
        self.port = int(port)
        self.username = str(username or "")
        self._password = str(password or "")
        self.profile_token = str(profile_token) if profile_token is not None else None
        self.timeout_seconds = float(timeout_seconds)
        self._client_factory = client_factory
        self._client = None
        self._ptz = None
        self._connected = False
        self._last_error: str | None = None

    def _clean_error(self, exc: Exception) -> str:
        message = str(exc)
        if self._password:
            message = message.replace(self._password, "***")
        return message

    @staticmethod
    def _token(profile) -> str | None:
        if isinstance(profile, dict):
            value = profile.get("token") or profile.get("_token")
        else:
            value = getattr(profile, "token", None) or getattr(profile, "_token", None)
        return str(value) if value is not None else None

    def connect(self) -> None:
        if self._connected:
            return
        try:
            if self._client_factory is None:
                try:
                    from onvif import ONVIFCamera as Client
                    from zeep.transports import Transport
                except ImportError as exc:
                    raise CameraConnectionError(
                        "ONVIF support requires the onvif-zeep package; rerun setup_windows.bat."
                    ) from exc
                transport = Transport(timeout=self.timeout_seconds, operation_timeout=self.timeout_seconds)
                client = Client(
                    self.host,
                    self.port,
                    self.username,
                    self._password,
                    no_cache=True,
                    transport=transport,
                )
            else:
                client = self._client_factory(self.host, self.port, self.username, self._password)

            media = client.create_media_service()
            profiles = list(media.GetProfiles())
            if not profiles:
                raise CameraConnectionError("ONVIF camera returned no media profiles.")
            tokens = [token for token in (self._token(p) for p in profiles) if token]
            if self.profile_token is None:
                self.profile_token = tokens[0] if tokens else None
            elif self.profile_token not in tokens:
                raise CameraConnectionError(
                    f"Configured ONVIF profile token {self.profile_token!r} was not returned by the camera."
                )
            if not self.profile_token:
                raise CameraConnectionError("ONVIF media profile did not contain a token.")

            ptz = client.create_ptz_service()
            # Read-only status call verifies the selected profile and PTZ service.
            ptz.GetStatus({"ProfileToken": self.profile_token})
        except Exception as exc:
            self._client = None
            self._ptz = None
            self._connected = False
            self._last_error = self._clean_error(exc)
            if isinstance(exc, CameraConnectionError):
                raise
            raise CameraConnectionError(
                f"Could not connect to ONVIF camera {self.host}:{self.port}: {self._last_error}"
            ) from exc
        self._client = client
        self._ptz = ptz
        self._connected = True
        self._last_error = None

    def health(self) -> CameraHealth:
        if self._connected:
            return CameraHealth(
                CameraState.READY,
                f"ONVIF {self.host}:{self.port} profile={self.profile_token}",
                connected=True,
            )
        state = CameraState.ERROR if self._last_error else CameraState.DISCONNECTED
        return CameraHealth(state, "ONVIF camera is not connected", last_error=self._last_error)

    def _require_ptz(self):
        if not self._connected or self._ptz is None or not self.profile_token:
            raise CameraConnectionError("ONVIF PTZ service is not connected.")
        return self._ptz

    def goto_preset(self, preset: int, label: str = "") -> None:
        ptz = self._require_ptz()
        try:
            ptz.GotoPreset({"ProfileToken": self.profile_token, "PresetToken": str(preset)})
        except Exception as exc:
            self._last_error = self._clean_error(exc)
            raise CameraCommandError(f"ONVIF GotoPreset failed: {self._last_error}") from exc

    def stop(self) -> None:
        ptz = self._require_ptz()
        try:
            ptz.Stop({"ProfileToken": self.profile_token, "PanTilt": True, "Zoom": True})
        except Exception as exc:
            self._last_error = self._clean_error(exc)
            raise CameraCommandError(f"ONVIF Stop failed: {self._last_error}") from exc

    def home(self) -> None:
        ptz = self._require_ptz()
        try:
            ptz.GotoHomePosition({"ProfileToken": self.profile_token})
        except Exception as exc:
            self._last_error = self._clean_error(exc)
            raise CameraCommandError(f"ONVIF GotoHomePosition failed: {self._last_error}") from exc

    def disconnect(self) -> None:
        client, self._client = self._client, None
        self._ptz = None
        self._connected = False
        transport = getattr(client, "transport", None)
        session = getattr(transport, "session", None)
        close = getattr(session, "close", None)
        if callable(close):
            close()
