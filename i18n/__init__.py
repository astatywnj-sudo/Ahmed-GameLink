"""Tiny JSON-based i18n loader.

- Default language: Arabic (Spec section 3).
- Language can be switched at runtime from Settings with no restart:
  every UI text is refreshed via ui.i18n_mixin.TranslatableMixin.
- Technical terms (DNS, TCP, TLS, RTT, ms) stay in English inside the
  Arabic file (Spec section 3).
"""

import json
from pathlib import Path

_DIR = Path(__file__).parent
_available = {"ar": _DIR / "ar.json", "en": _DIR / "en.json"}

_current = "ar"
_translations: dict = {}


def available_languages() -> list[str]:
    return sorted(_available)


def current() -> str:
    return _current


def load(lang: str) -> None:
    """Switch the active language. Falls back to Arabic on any problem."""
    global _current, _translations
    path = _available.get(lang)
    if path is None or not path.is_file():
        lang, path = "ar", _available["ar"]
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("translation file must contain an object")
        _translations = data
        _current = lang
    except (OSError, json.JSONDecodeError, ValueError):
        # Keep the previous translations rather than losing all texts.
        pass


def tr(key: str, **params) -> str:
    """Translate a key; missing keys return the key itself so problems
    are visible during development instead of silently showing ''. """
    text = _translations.get(key, key)
    if params:
        try:
            text = text.format(**params)
        except (KeyError, IndexError, ValueError):
            pass
    return text
