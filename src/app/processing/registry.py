"""Registry of processing modes. Modes are discovered at startup; the API lists whatever is here."""

from __future__ import annotations

import logging

from app.i18n import DEFAULT_LANG, tr
from app.processing.base import ProcessingMode

log = logging.getLogger(__name__)


class Registry:
    def __init__(self) -> None:
        self._modes: dict[str, ProcessingMode] = {}

    def register(self, mode: ProcessingMode) -> None:
        if mode.id in self._modes:
            raise ValueError(f"mode id already registered: {mode.id}")
        self._modes[mode.id] = mode
        log.info("registered processing mode %s", mode.id)

    def list(self) -> list[ProcessingMode]:
        return list(self._modes.values())

    def get(self, mode_id: str) -> ProcessingMode | None:
        return self._modes.get(mode_id)

    def to_dict(self, lang: str = DEFAULT_LANG) -> list[dict]:
        return [
            {
                "id": m.id,
                "name": tr(m.name, lang),
                "description": tr(m.description, lang),
                "params": [p.to_dict(lang) for p in m.params()],
            }
            for m in self._modes.values()
        ]
