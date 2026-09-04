from pathlib import Path


def test_console_python_sources_are_ascii_safe():
    project = Path(__file__).resolve().parents[1]
    for relative in ("speakerptz/main.py", "speakerptz/audio/identifier.py"):
        (project / relative).read_text(encoding="utf-8").encode("ascii")
