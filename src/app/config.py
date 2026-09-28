"""Runtime configuration. Every value comes from an environment variable with a default."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


@dataclass
class Settings:
    """Application settings.

    LCP_DIR            directory with .lcp lens profiles
    DATA_DIR           writable directory for uploads and results
    RAWTHERAPEE_CLI    command used to run RawTherapee (may contain arguments)
    PROCESS_TIMEOUT    seconds before a RawTherapee run is killed
    RESULT_TTL         seconds to keep uploads and results on disk
    MAX_UPLOAD_MB      reject uploads larger than this
    JPEG_QUALITY       quality of the processed JPEG
    """

    lcp_dir: Path = field(default_factory=lambda: _env_path("LCP_DIR", Path.cwd() / "LCP"))
    data_dir: Path = field(
        default_factory=lambda: _env_path("DATA_DIR", Path.cwd() / ".data")
    )
    rawtherapee_cli: str = field(
        default_factory=lambda: os.environ.get("RAWTHERAPEE_CLI", "rawtherapee-cli")
    )
    process_timeout: int = field(default_factory=lambda: _env_int("PROCESS_TIMEOUT", 300))
    result_ttl: int = field(default_factory=lambda: _env_int("RESULT_TTL", 3600))
    max_upload_mb: int = field(default_factory=lambda: _env_int("MAX_UPLOAD_MB", 200))
    jpeg_quality: int = field(default_factory=lambda: _env_int("JPEG_QUALITY", 95))

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024
