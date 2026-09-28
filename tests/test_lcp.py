from __future__ import annotations

from pathlib import Path

from app.processing.lcp import LcpIndex, normalize_lens_name, parse_lcp


def test_index_loads_every_file_and_profile(lcp_dir: Path) -> None:
    index = LcpIndex.load(lcp_dir)
    assert len(index) == 110
    assert index.profile_count == 114
    raw_files = [f for f in index.files if f.camera_raw]
    assert len(raw_files) == 55
    assert all(f.id.endswith("- RAW.lcp") for f in raw_files)


def test_lrm_files_hold_two_profiles(lcp_dir: Path) -> None:
    path = lcp_dir / "Apple iPhone (Apple iPhone 16 Pro back camera 2.22mm f2.2 - LRM).lcp"
    lcp = parse_lcp(path)
    assert len(lcp.profiles) == 2
    assert lcp.camera_raw is False


def test_profile_fields(lcp_dir: Path) -> None:
    lcp = parse_lcp(lcp_dir / "Apple iPhone (Apple iPhone 15 Pro back camera 9mm f2.8).lcp")
    p = lcp.first
    assert p.make == "Apple"
    assert p.model == "iPhone"
    assert p.lens == "iPhone 15 Pro back camera 9mm f/2.8"
    assert p.image_width == 4032 and p.image_length == 3024
    assert p.focal_length == 9
    assert p.alternate_lens_names == ("iPhone 15 Pro back triple camera 9mm f/2.8",)
    assert p.has_perspective is True
    assert p.has_vignette is False
    assert p.has_chromatic_aberration is False
    assert lcp.label == "Apple iPhone 15 Pro back camera 9mm f/2.8"


def test_no_profile_has_chromatic_aberration_and_four_have_vignette(lcp_dir: Path) -> None:
    index = LcpIndex.load(lcp_dir)
    assert not any(f.has_chromatic_aberration for f in index.files)
    assert sum(len([p for p in f.profiles if p.has_vignette]) for f in index.files) == 4


def test_suggest_by_exif_lens_model(lcp_dir: Path) -> None:
    index = LcpIndex.load(lcp_dir)
    exif_lens = "iPhone 15 Pro back triple camera 9mm f/2.8"
    jpeg = index.suggest(exif_lens, camera_raw=False)
    raw = index.suggest(exif_lens, camera_raw=True)
    assert jpeg is not None and jpeg.id == "Apple iPhone (Apple iPhone 15 Pro back camera 9mm f2.8).lcp"
    assert raw is not None and raw.id == "Apple iPhone (Apple iPhone 15 Pro back camera 9mm f2.8) - RAW.lcp"
    assert index.suggest(None, camera_raw=False) is None
    assert index.suggest("Canon EF 50mm", camera_raw=False) is None


def test_normalize_lens_name() -> None:
    assert normalize_lens_name("iPhone 15 Pro back camera 9mm f/2.8") == "iphone15probackcamera9mmf2.8"
    assert normalize_lens_name("  ") == ""
