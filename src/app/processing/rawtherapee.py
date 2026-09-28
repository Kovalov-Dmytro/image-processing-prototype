"""Thin wrapper around rawtherapee-cli.

RawTherapee is driven with a generated .pp3 processing profile. Only the
sections we set are written; RawTherapee fills the rest with its defaults, so
"before" and "after" renders differ only in the lens correction section.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.processing.base import ProcessingError


@dataclass(frozen=True)
class LensProfileOptions:
    """Maps to the [LensProfile] section of a .pp3 file."""

    lcp_file: Path | None = None
    distortion: bool = True
    vignette: bool = True
    chromatic_aberration: bool = False

    @property
    def enabled(self) -> bool:
        return self.lcp_file is not None and (
            self.distortion or self.vignette or self.chromatic_aberration
        )


def _bool(value: bool) -> str:
    return "true" if value else "false"


def build_pp3(lens: LensProfileOptions) -> str:
    """Render a partial .pp3 profile."""
    lines = ["[LensProfile]"]
    if lens.enabled:
        lines += [
            "LcMode=lcp",
            f"LCPFile={lens.lcp_file}",
            f"UseDistortion={_bool(lens.distortion)}",
            f"UseVignette={_bool(lens.vignette)}",
            f"UseCA={_bool(lens.chromatic_aberration)}",
        ]
    else:
        lines += [
            "LcMode=none",
            "LCPFile=",
            "UseDistortion=false",
            "UseVignette=false",
            "UseCA=false",
        ]
    return "\n".join(lines) + "\n"


@dataclass
class RunResult:
    output_path: Path
    command: list[str]
    stdout: str
    stderr: str

    @property
    def log(self) -> str:
        parts = ["$ " + " ".join(shlex.quote(c) for c in self.command)]
        if self.stdout.strip():
            parts.append(self.stdout.strip())
        if self.stderr.strip():
            parts.append(self.stderr.strip())
        return "\n".join(parts)


class RawTherapee:
    def __init__(self, cli: str = "rawtherapee-cli", timeout: int = 300) -> None:
        self._cli = shlex.split(cli)
        self._timeout = timeout

    @property
    def executable(self) -> str:
        return self._cli[0]

    def is_available(self) -> bool:
        return shutil.which(self.executable) is not None or Path(self.executable).exists()

    def render(
        self,
        input_path: Path,
        output_dir: Path,
        pp3_text: str,
        jpeg_quality: int = 95,
    ) -> RunResult:
        """Render input_path to <output_dir>/<input stem>.jpg using the given profile text."""
        if not self.is_available():
            raise ProcessingError(
                f"RawTherapee is not available ({self.executable} not found). "
                "Run the app inside the Docker image or set RAWTHERAPEE_CLI."
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        pp3_path = output_dir / "profile.pp3"
        pp3_path.write_text(pp3_text, encoding="utf-8")

        command = [
            *self._cli,
            "-o",
            str(output_dir),
            "-p",
            str(pp3_path),
            # -a: process the file whatever its extension. Without it RawTherapee only
            # accepts the "parsed extensions" from its options file, which excludes PNG.
            "-a",
            f"-j{int(jpeg_quality)}",
            "-js3",
            "-Y",
            "-c",
            str(input_path),
        ]
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProcessingError(
                f"RawTherapee did not finish in {self._timeout} s"
            ) from exc

        expected = output_dir / f"{input_path.stem}.jpg"
        if proc.returncode != 0 or not expected.exists():
            detail = (proc.stderr or proc.stdout or "").strip()
            raise ProcessingError(
                f"RawTherapee failed (exit code {proc.returncode}). {detail}".strip()
            )
        return RunResult(
            output_path=expected,
            command=command,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )
