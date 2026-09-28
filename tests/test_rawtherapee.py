from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.processing.base import ProcessingError
from app.processing.rawtherapee import LensProfileOptions, RawTherapee, build_pp3


def test_build_pp3_with_profile(tmp_path: Path) -> None:
    lcp = tmp_path / "a b.lcp"
    text = build_pp3(LensProfileOptions(lcp_file=lcp, distortion=True, vignette=False))
    assert "[LensProfile]" in text
    assert "LcMode=lcp" in text
    assert f"LCPFile={lcp}" in text
    assert "UseDistortion=true" in text
    assert "UseVignette=false" in text
    assert "UseCA=false" in text


def test_build_pp3_without_profile() -> None:
    text = build_pp3(LensProfileOptions(lcp_file=None))
    assert "LcMode=none" in text
    assert "UseDistortion=false" in text


def test_render_with_fake_cli(tmp_path: Path, fake_rt_cli: str, jpeg_bytes: bytes) -> None:
    src = tmp_path / "input.jpg"
    src.write_bytes(jpeg_bytes)
    rt = RawTherapee(fake_rt_cli, timeout=30)
    assert rt.is_available()
    result = rt.render(src, tmp_path / "out", build_pp3(LensProfileOptions(lcp_file=src)), 80)
    assert result.output_path == tmp_path / "out" / "input.jpg"
    assert result.output_path.exists()
    assert "-j80" in result.command
    assert (tmp_path / "out" / "profile.pp3").exists()
    with Image.open(result.output_path) as im:
        assert im.size == (64, 48)


def test_render_reports_failure(tmp_path: Path, fake_rt_cli: str, jpeg_bytes: bytes) -> None:
    src = tmp_path / "input.jpg"
    src.write_bytes(jpeg_bytes)
    rt = RawTherapee(fake_rt_cli, timeout=30)
    with pytest.raises(ProcessingError) as exc:
        rt.render(src, tmp_path / "out", "[LensProfile]\nFAKE_RT_FAIL=1\n")
    assert "forced failure" in str(exc.value)


def test_missing_cli_is_a_processing_error(tmp_path: Path) -> None:
    rt = RawTherapee("/nonexistent/rawtherapee-cli")
    assert not rt.is_available()
    with pytest.raises(ProcessingError):
        rt.render(tmp_path / "x.jpg", tmp_path / "out", "")
