"""Common interface every processing mode implements."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.i18n import DEFAULT_LANG, Text, tr


class ProcessingError(Exception):
    """Raised when a mode cannot produce a result. The message is shown to the user."""


@dataclass(frozen=True)
class ParamOption:
    value: str
    label: Text
    group: Text | None = None


@dataclass(frozen=True)
class ParamSpec:
    """Describes one user-facing parameter so the UI can render it without mode-specific code.

    type is one of: "select", "bool", "number".
    """

    name: str
    label: Text
    type: str
    default: Any = None
    help: Text = ""
    options: tuple[ParamOption, ...] = ()
    min: float | None = None
    max: float | None = None
    step: float | None = None
    section: Text = ""

    def to_dict(self, lang: str = DEFAULT_LANG) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "label": tr(self.label, lang),
            "type": self.type,
            "default": self.default,
            "help": tr(self.help, lang),
            "section": tr(self.section, lang),
        }
        if self.type == "select":
            data["options"] = [
                {"value": o.value, "label": tr(o.label, lang), "group": tr(o.group, lang) or None}
                for o in self.options
            ]
        if self.type == "number":
            data.update({"min": self.min, "max": self.max, "step": self.step})
        return data


@dataclass
class ProcessRequest:
    """Input to a mode. All paths are local files owned by the caller."""

    input_path: Path
    work_dir: Path
    params: dict[str, Any] = field(default_factory=dict)
    lang: str = DEFAULT_LANG


@dataclass(frozen=True)
class ExtraFile:
    """An additional downloadable artifact produced by a mode (CSV, JSON, ...)."""

    name: str  # file name used in URLs, e.g. "beads.csv"
    path: Path
    label: str  # already translated by the mode
    media_type: str = "application/octet-stream"


@dataclass
class ProcessResult:
    """Output of a mode.

    processed_path  the result image (browser viewable: JPEG or PNG)
    original_path   what to show as "before". None means the input file itself.
    log             free-form text for the UI (tool output, notes)
    info            small structured details for the UI. Conventions the UI knows:
                    info["notes"]  list[str]
                    info["report"] {"stats": [{label, value}],
                                    "histogram": {title, unit, bins: [{lo, hi, count, percent}]},
                                    "tables": [{title, columns: [...], rows: [[...]]}]}
    files           extra downloadable files
    """

    processed_path: Path
    original_path: Path | None = None
    log: str = ""
    info: dict[str, Any] = field(default_factory=dict)
    files: list[ExtraFile] = field(default_factory=list)


class ProcessingMode(Protocol):
    id: str
    name: Text
    description: Text

    def params(self) -> list[ParamSpec]: ...

    def process(self, request: ProcessRequest) -> ProcessResult: ...
