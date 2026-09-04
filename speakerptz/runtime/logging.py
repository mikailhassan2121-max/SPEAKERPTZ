from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime


def setup_logging(log_dir: str = "logs") -> logging.Logger:
    path = Path(log_dir)
    path.mkdir(parents=True, exist_ok=True)
    logfile = path / f"speakerptz-{datetime.now():%Y%m%d}.log"

    logger = logging.getLogger("speakerptz")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    handler = RotatingFileHandler(logfile, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)
    return logger


def event(logger: logging.Logger, kind: str, **fields) -> None:
    payload = {"event": kind, **fields}
    logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))
