"""Processing modes. Each module here is one mode; build_registry wires them up.

Modes are imported lazily inside build_registry so that a mode whose optional
dependency is broken disables only that mode, not the whole application.
"""

from __future__ import annotations

import logging

from app.config import Settings
from app.processing.registry import Registry

log = logging.getLogger(__name__)


def build_registry(settings: Settings) -> Registry:
    registry = Registry()

    try:
        from app.processing.modes.lens_correction import LensCorrectionMode

        registry.register(LensCorrectionMode.from_settings(settings))
    except Exception:  # noqa: BLE001 - keep the app up if one mode fails to load
        log.exception("failed to load mode lens_correction")

    try:
        from app.processing.modes.bead_analysis import BeadAnalysisMode

        registry.register(BeadAnalysisMode.from_settings(settings))
    except Exception:  # noqa: BLE001
        log.exception("failed to load mode bead_analysis")

    try:
        from app.processing.modes.cellpose_beads import CellposeBeadsMode

        mode = CellposeBeadsMode.from_settings(settings)
        if mode.available:
            registry.register(mode)
        else:
            log.warning("cellpose is not installed; mode cellpose_beads disabled")
    except Exception:  # noqa: BLE001
        log.exception("failed to load mode cellpose_beads")

    return registry
