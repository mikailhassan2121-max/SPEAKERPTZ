from dataclasses import dataclass


@dataclass(frozen=True)
class PersonRoute:
    mic_channel: int
    name: str
    camera: int
    preset: int
