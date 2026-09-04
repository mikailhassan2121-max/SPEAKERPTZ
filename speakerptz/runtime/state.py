from __future__ import annotations

import json
import os
import time
from pathlib import Path


class RuntimeState:
    """Small crash-safe state record; never restores AUTO or camera authority."""

    def __init__(self, path: str, clock=None, wall_clock=None):
        self.path = Path(path)
        self._clock = clock or time.monotonic
        self._wall_clock = wall_clock or time.time
        self.started = self._clock()
        self.previous = self.read()

    def read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}

    @property
    def previous_unclean_shutdown(self) -> bool:
        return bool(self.previous) and self.previous.get("clean_shutdown") is False

    def _write(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.path)

    def mark_started(self, version: str, mode: str) -> None:
        self._write(
            {
                "version": str(version),
                "mode": str(mode),
                "pid": os.getpid(),
                "started_at_epoch": self._wall_clock(),
                "heartbeat_at_epoch": self._wall_clock(),
                "uptime_seconds": 0.0,
                "clean_shutdown": False,
                "auto_enabled": False,
            }
        )

    def heartbeat(self, *, auto_enabled: bool, audio_ok: bool, camera_states: dict) -> None:
        current = self.read()
        current.update(
            {
                "heartbeat_at_epoch": self._wall_clock(),
                "uptime_seconds": round(self._clock() - self.started, 3),
                "auto_enabled": bool(auto_enabled),
                "audio_ok": bool(audio_ok),
                "camera_states": {str(key): str(value) for key, value in camera_states.items()},
                "clean_shutdown": False,
            }
        )
        self._write(current)

    def mark_clean_shutdown(self) -> None:
        current = self.read()
        current.update(
            {
                "heartbeat_at_epoch": self._wall_clock(),
                "uptime_seconds": round(self._clock() - self.started, 3),
                "clean_shutdown": True,
                "auto_enabled": False,
            }
        )
        self._write(current)
