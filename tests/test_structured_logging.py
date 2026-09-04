import json
from logging.handlers import RotatingFileHandler

from speakerptz.runtime.logging import event, setup_logging


def test_events_are_json_lines_and_rotation_is_bounded(tmp_path):
    logger = setup_logging(str(tmp_path))
    event(logger, "health_heartbeat", audio_ok=True, camera_states={"1": "ready"})
    handler = logger.handlers[0]
    handler.flush()

    assert isinstance(handler, RotatingFileHandler)
    assert handler.maxBytes == 2_000_000
    assert handler.backupCount == 5
    payload = json.loads(next(tmp_path.glob("speakerptz-*.log")).read_text(encoding="utf-8"))
    assert payload["event"] == "health_heartbeat"
    assert payload["audio_ok"] is True
    assert payload["level"] == "INFO"
    assert payload["timestamp"].endswith("+00:00")
