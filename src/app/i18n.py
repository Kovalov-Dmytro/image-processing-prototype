"""Tiny bilingual helper. Texts are plain strings or {"en": ..., "ru": ...} dicts."""

from __future__ import annotations

from typing import Union

LANGS = ("en", "ru")
DEFAULT_LANG = "en"

Text = Union[str, dict[str, str]]


def t(en: str, ru: str) -> dict[str, str]:
    return {"en": en, "ru": ru}


def normalize_lang(value: str | None) -> str:
    """Map a language tag or Accept-Language header to a supported code."""
    if not value:
        return DEFAULT_LANG
    for part in value.split(","):
        code = part.split(";")[0].strip().lower()
        if not code:
            continue
        code = code.split("-")[0]
        if code in LANGS:
            return code
    return DEFAULT_LANG


def tr(text: Text | None, lang: str) -> str:
    """Resolve a text for a language, falling back to English, then to any value."""
    if text is None:
        return ""
    if isinstance(text, str):
        return text
    return text.get(lang) or text.get(DEFAULT_LANG) or next(iter(text.values()), "")
