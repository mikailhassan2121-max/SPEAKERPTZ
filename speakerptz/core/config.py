from pathlib import Path
import yaml
from .models import PersonRoute


def load_config(path: str):
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    routes = {
        int(p["mic_channel"]): PersonRoute(
            mic_channel=int(p["mic_channel"]),
            name=str(p["name"]),
            camera=int(p["camera"]),
            preset=int(p["preset"]),
        )
        for p in data["people"]
    }
    return data, routes
