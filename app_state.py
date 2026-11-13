"""User application state (settings only — no network data).

Spec section 4 (privacy):
- Stored in the user's own profile (%APPDATA%), never in system folders.
- Contains ONLY user preferences (currently: language).
- Never stores passwords, account data, or IP addresses.
"""

import copy
import json
import os
from pathlib import Path

# Everything the app persists today. New preferences must be added here
# so that save()/reset() stay complete and honest.
DEFAULTS = {
    "language": "ar",  # Spec section 3: Arabic (RTL) is the default.
}


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "AhmedGameLink"


class AppState:
    """Loads/saves settings.json atomically enough for a 4GB-RAM machine:
    a tiny file, read once at startup and written only when a value changes."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config_dir() / "settings.json")
        self.settings: dict = self._load()

    # ------------------------------------------------------------------ load
    def _load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("settings.json must contain an object")
            merged = copy.deepcopy(DEFAULTS)
            merged.update({k: v for k, v in data.items() if k in DEFAULTS})
            return merged
        except FileNotFoundError:
            return copy.deepcopy(DEFAULTS)
        except (json.JSONDecodeError, OSError, ValueError):
            # Corrupted settings file: fall back to defaults, never crash.
            return copy.deepcopy(DEFAULTS)

    # ------------------------------------------------------------------ save
    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.settings, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)  # atomic on Windows
        except OSError:
            # Settings are a convenience, not a requirement: never crash
            # the app because the disk refused a write.
            pass

    def set(self, key: str, value) -> None:
        self.settings[key] = value
        self.save()

    # ----------------------------------------------------------------- reset
    def reset(self) -> None:
        self.settings = copy.deepcopy(DEFAULTS)
        self.save()
