from __future__ import annotations

import io
import shlex
import sys
from pathlib import Path

import pytest
from PIL import Image

from app.config import Settings

ROOT = Path(__file__).resolve().parent.parent
LCP_DIR = ROOT / "LCP"
FAKE_RT = Path(__file__).resolve().parent / "fake_rawtherapee.py"


@pytest.fixture(scope="session")
def lcp_dir() -> Path:
    assert LCP_DIR.is_dir(), "LCP directory missing"
    return LCP_DIR


@pytest.fixture
def fake_rt_cli() -> str:
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(FAKE_RT))}"


@pytest.fixture
def settings(tmp_path: Path, lcp_dir: Path, fake_rt_cli: str) -> Settings:
    return Settings(
        lcp_dir=lcp_dir,
        data_dir=tmp_path / "data",
        rawtherapee_cli=fake_rt_cli,
        process_timeout=60,
        result_ttl=3600,
        max_upload_mb=5,
        jpeg_quality=90,
    )


def make_image_bytes(fmt: str = "JPEG", size: tuple[int, int] = (64, 48)) -> bytes:
    im = Image.new("RGB", size, (200, 40, 40))
    for x in range(size[0]):
        for y in range(size[1]):
            if (x // 8 + y // 8) % 2:
                im.putpixel((x, y), (40, 40, 200))
    buf = io.BytesIO()
    im.save(buf, fmt)
    return buf.getvalue()


@pytest.fixture
def jpeg_bytes() -> bytes:
    return make_image_bytes("JPEG")


@pytest.fixture
def tiff_bytes() -> bytes:
    return make_image_bytes("TIFF")
