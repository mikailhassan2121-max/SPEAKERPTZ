from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime, timezone


class StructuredLogFormatter(logging.Formatter):
    """Emit one self-contained JSON object per event."""

    def format(self, record: logging.LogRecord) -> str:
        try:
            payload = json.loads(record.getMessage())
        except (TypeError, json.JSONDecodeError):
            payload = {"event": "log_message", "message": record.getMessage()}
        return json.dumps(
            {
                "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                "level": record.levelname,
                **payload,
            },
            ensure_ascii=False,
            sort_keys=True,
        )


def setup_logging(log_dir: str = "logs") -> logging.Logger:
    path = Path(log_dir)
    path.mkdir(parents=True, exist_ok=True)
    logfile = path / f"speakerptz-{datetime.now():%Y%m%d}.log"

    logger = logging.getLogger("speakerptz")
    logger.setLevel(logging.INFO)
    for existing in logger.handlers:
        existing.close()
    logger.handlers.clear()
    logger.propagate = False

    handler = RotatingFileHandler(logfile, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(StructuredLogFormatter())
    logger.addHandler(handler)
    return logger


def event(logger: logging.Logger, kind: str, **fields) -> None:
    payload = {"event": kind, **fields}
    logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))
