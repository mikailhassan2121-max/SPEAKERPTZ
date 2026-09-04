from __future__ import annotations

from abc import ABC, abstractmethod

from .models import CameraHealth


class CameraError(RuntimeError):
    """Base error raised by a camera driver."""


class CameraConnectionError(CameraError):
    """The driver could not establish or maintain camera communication."""


class CameraCommandError(CameraError):
    """The camera rejected a command or did not acknowledge it."""


class CameraDriver(ABC):
    """Protocol-neutral high-level PTZ camera interface."""

    @abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> CameraHealth:
        raise NotImplementedError

    @abstractmethod
    def goto_preset(self, preset: int, label: str = "") -> None:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        raise NotImplementedError

    def home(self) -> None:
        raise CameraCommandError("Home is not supported by this camera driver.")

    @abstractmethod
    def disconnect(self) -> None:
        raise NotImplementedError
