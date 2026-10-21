"""Ustawienia Go1 Pilot zapisywane w settings.json obok programu."""
import json
from pathlib import Path

PATH = Path(__file__).parent / "settings.json"

DEFAULTS = {
    "host": "192.168.12.1",
    "auto_connect": False,
    "max_speed": 0.6,          # górny limit suwaka prędkości
    "start_speed": 0.4,
    "auto_walk": True,         # klawisze ruchu same włączają tryb „Chód”
    "confirm_damping": True,
    "move_seconds": 2.0,       # jak długo trwa ruch z komendy głosowej
    "spin_seconds": 3.5,
    "voice_strictness": "normal",  # strict / normal / loose
    "mic_device": None,
    "pi_user": "pi",
    "pi_password": "123",
    "jetson_user": "unitree",
    "jetson_password": "123",
    "camera_index": 0,
    "camera_quality": "medium",  # low / medium / high
}

LIMITS = {
    "max_speed": (0.1, 1.0), "start_speed": (0.1, 1.0),
    "move_seconds": (0.5, 6.0), "spin_seconds": (1.0, 8.0),
}
CHOICES = {
    "voice_strictness": ("strict", "normal", "loose"),
    "camera_quality": ("low", "medium", "high"),
}


def load(path=PATH):
    data = dict(DEFAULTS)
    try:
        data.update(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return clean(data)


def save(data, path=PATH):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clean(data):
    """Zostawia tylko znane klucze z poprawnymi typami i zakresami."""
    out = {}
    for key, default in DEFAULTS.items():
        value = data.get(key, default)
        try:
            if isinstance(default, bool):
                value = bool(value)
            elif isinstance(default, float):
                lo, hi = LIMITS[key]
                value = round(max(lo, min(hi, float(value))), 2)
            elif isinstance(default, int):
                value = max(0, int(value))
            elif key in CHOICES:
                value = value if value in CHOICES[key] else default
            elif key == "mic_device":
                value = None if value in (None, "") else int(value)
            else:
                value = str(value)
        except (TypeError, ValueError):
            value = default
        out[key] = value
    out["start_speed"] = min(out["start_speed"], out["max_speed"])
    return out
