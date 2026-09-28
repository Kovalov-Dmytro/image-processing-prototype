"""Reader and index for Adobe Lens Correction Profiles (.lcp).

An .lcp file is XMP/RDF XML. Profiles live under photoshop:CameraProfiles as an
rdf:Seq of rdf:Description elements in the stCamera namespace. A file may hold
more than one profile, so everything iterates the sequence.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

NS = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "photoshop": "http://ns.adobe.com/photoshop/1.0/",
    "stCamera": "http://ns.adobe.com/photoshop/1.0/camera-profile",
}
_ST = "{%s}" % NS["stCamera"]
_RDF = "{%s}" % NS["rdf"]
_PS = "{%s}" % NS["photoshop"]

_CA_TAGS = (
    "ChromaticGreenModel",
    "ChromaticRedGreenModel",
    "ChromaticBlueGreenModel",
)


def _float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _int(value: str | None) -> int | None:
    f = _float(value)
    return int(f) if f is not None else None


@dataclass(frozen=True)
class LcpProfile:
    lens: str
    lens_pretty_name: str
    profile_name: str
    make: str
    model: str
    camera_raw: bool
    image_width: int | None
    image_length: int | None
    focal_length: float | None
    aperture_value: float | None
    focus_distance: float | None
    sensor_format_factor: float | None
    alternate_lens_names: tuple[str, ...]
    has_perspective: bool
    has_vignette: bool
    has_chromatic_aberration: bool

    @property
    def lens_names(self) -> tuple[str, ...]:
        return (self.lens, *self.alternate_lens_names)


@dataclass(frozen=True)
class LcpFile:
    path: Path
    profiles: tuple[LcpProfile, ...]

    @property
    def id(self) -> str:
        return self.path.name

    @property
    def camera_raw(self) -> bool:
        return all(p.camera_raw for p in self.profiles)

    @property
    def first(self) -> LcpProfile:
        return self.profiles[0]

    @property
    def label(self) -> str:
        suffix = " [RAW]" if self.camera_raw else ""
        return f"{self.first.lens_pretty_name}{suffix}"

    @property
    def has_vignette(self) -> bool:
        return any(p.has_vignette for p in self.profiles)

    @property
    def has_chromatic_aberration(self) -> bool:
        return any(p.has_chromatic_aberration for p in self.profiles)

    @property
    def lens_names(self) -> set[str]:
        return {name for p in self.profiles for name in p.lens_names}

    def to_dict(self) -> dict:
        first = self.first
        return {
            "id": self.id,
            "label": self.label,
            "lens": first.lens,
            "lens_pretty_name": first.lens_pretty_name,
            "camera_raw": self.camera_raw,
            "image_width": first.image_width,
            "image_length": first.image_length,
            "focal_length": first.focal_length,
            "aperture_value": first.aperture_value,
            "profiles": len(self.profiles),
            "has_vignette": self.has_vignette,
            "has_chromatic_aberration": self.has_chromatic_aberration,
        }


def _has_descendant(elem: ET.Element, local_name: str) -> bool:
    """True if any element in the subtree has this stCamera tag.

    Sub-models nest: VignetteModel sits inside PerspectiveModel/rdf:Description,
    so a direct-child lookup misses it.
    """
    return next(elem.iter(_ST + local_name), None) is not None


def _parse_profile(desc: ET.Element) -> LcpProfile:
    def attr(name: str) -> str | None:
        return desc.get(_ST + name)

    alternates: list[str] = []
    alt = desc.find("stCamera:AlternateLensNames", NS)
    if alt is not None:
        alternates = [li.text.strip() for li in alt.iter(_RDF + "li") if li.text]

    return LcpProfile(
        lens=attr("Lens") or "",
        lens_pretty_name=attr("LensPrettyName") or attr("Lens") or "",
        profile_name=attr("ProfileName") or "",
        make=attr("Make") or "",
        model=attr("Model") or "",
        camera_raw=(attr("CameraRawProfile") or "").lower() == "true",
        image_width=_int(attr("ImageWidth")),
        image_length=_int(attr("ImageLength")),
        focal_length=_float(attr("FocalLength")),
        aperture_value=_float(attr("ApertureValue")),
        focus_distance=_float(attr("FocusDistance")),
        sensor_format_factor=_float(attr("SensorFormatFactor")),
        alternate_lens_names=tuple(alternates),
        has_perspective=_has_descendant(desc, "PerspectiveModel"),
        has_vignette=_has_descendant(desc, "VignetteModel"),
        has_chromatic_aberration=any(_has_descendant(desc, tag) for tag in _CA_TAGS),
    )


def parse_lcp(path: Path) -> LcpFile:
    """Parse one .lcp file. Raises ValueError when no profile is found."""
    tree = ET.parse(path)
    root = tree.getroot()
    profiles = []
    for camera_profiles in root.iter(_PS + "CameraProfiles"):
        for li in camera_profiles.iter(_RDF + "li"):
            desc = li.find("rdf:Description", NS)
            if desc is not None and desc.get(_ST + "ProfileName") is not None:
                profiles.append(_parse_profile(desc))
    if not profiles:
        raise ValueError(f"no camera profiles found in {path}")
    return LcpFile(path=path, profiles=tuple(profiles))


_NORMALIZE_RE = re.compile(r"[\s/_-]+")


def normalize_lens_name(name: str) -> str:
    """Make lens names comparable: lowercase, drop spaces, slashes, dashes."""
    return _NORMALIZE_RE.sub("", name.strip().lower())


class LcpIndex:
    """All .lcp files in a directory, loaded once."""

    def __init__(self, files: list[LcpFile]) -> None:
        self._files = sorted(files, key=lambda f: (f.camera_raw, f.label.lower()))
        self._by_id = {f.id: f for f in self._files}

    @classmethod
    def load(cls, directory: Path) -> "LcpIndex":
        files = []
        for path in sorted(directory.glob("*.lcp")):
            files.append(parse_lcp(path))
        return cls(files)

    def __len__(self) -> int:
        return len(self._files)

    @property
    def files(self) -> list[LcpFile]:
        return list(self._files)

    @property
    def profile_count(self) -> int:
        return sum(len(f.profiles) for f in self._files)

    def get(self, file_id: str) -> LcpFile | None:
        return self._by_id.get(file_id)

    def suggest(self, lens_model: str | None, camera_raw: bool) -> LcpFile | None:
        """Find the file whose lens (or alternate lens name) matches an EXIF LensModel."""
        if not lens_model:
            return None
        wanted = normalize_lens_name(lens_model)
        if not wanted:
            return None
        candidates = [f for f in self._files if f.camera_raw == camera_raw]
        for f in candidates:
            if any(normalize_lens_name(n) == wanted for n in f.lens_names):
                return f
        # Fall back to a substring match in either direction (handles minor naming drift).
        for f in candidates:
            for n in f.lens_names:
                norm = normalize_lens_name(n)
                if norm and (norm in wanted or wanted in norm):
                    return f
        return None
