from abc import ABC, abstractmethod


class CameraDriver(ABC):
    @abstractmethod
    def goto_preset(self, camera: int, preset: int, label: str = "") -> None:
        raise NotImplementedError
