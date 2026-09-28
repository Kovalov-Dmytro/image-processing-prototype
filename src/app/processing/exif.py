"""Minimal EXIF reading: enough to suggest a lens profile."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import exifread

RAW_EXTENSIONS = {".dng"}
BROWSER_EXTENSIONS = {".jpg", ".jpeg", ".png"}
SUPPORTED_EXTENSIONS = BROWSER_EXTENSIONS | {".tif", ".tiff"} | RAW_EXTENSIONS


@dataclass(frozen=True)
class ImageMeta:
    camera_make: str | None
    camera_model: str | None
    lens_model: str | None
    width: int | None
    height: int | None

    def to_dict(self) -> dict:
        return {
            "camera_make": self.camera_make,
            "camera_model": self.camera_model,
            "lens_model": self.lens_model,
            "width": self.width,
            "height": self.height,
        }


def is_raw(path: Path) -> bool:
    return path.suffix.lower() in RAW_EXTENSIONS


def is_browser_viewable(path: Path) -> bool:
    return path.suffix.lower() in BROWSER_EXTENSIONS


def _first(tags: dict, *names: str) -> str | None:
    for name in names:
        value = tags.get(name)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return None


def _first_int(tags: dict, *names: str) -> int | None:
    text = _first(tags, *names)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def read_meta(path: Path) -> ImageMeta:
    """Read a few EXIF tags. Never raises: unreadable files yield empty metadata."""
    try:
        with path.open("rb") as fh:
            tags = exifread.process_file(fh, details=False)
    except Exception:  # noqa: BLE001 - exifread raises many different types
        tags = {}
    return ImageMeta(
        camera_make=_first(tags, "Image Make"),
        camera_model=_first(tags, "Image Model"),
        lens_model=_first(tags, "EXIF LensModel", "Image LensModel", "MakerNote LensModel"),
        width=_first_int(tags, "EXIF ExifImageWidth", "Image ImageWidth"),
        height=_first_int(tags, "EXIF ExifImageLength", "Image ImageLength"),
    )
