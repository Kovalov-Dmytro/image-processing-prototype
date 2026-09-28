"""Stand-in for rawtherapee-cli used by the tests.

Understands the subset of arguments the app passes: -o <dir> -p <pp3> -jNN -js3 -Y -c <input>.
Writes <dir>/<input stem>.jpg. When the pp3 enables an LCP profile, the output is
tinted so tests can tell "before" from "after".
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageOps


def main(argv: list[str]) -> int:
    out_dir: Path | None = None
    pp3: Path | None = None
    inputs: list[Path] = []
    quality = 90
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "-o":
            out_dir = Path(argv[i + 1])
            i += 2
        elif arg == "-p":
            pp3 = Path(argv[i + 1])
            i += 2
        elif arg == "-c":
            inputs = [Path(a) for a in argv[i + 1 :]]
            break
        elif arg.startswith("-j") and arg[2:].isdigit():
            quality = int(arg[2:])
            i += 1
        else:
            i += 1

    if out_dir is None or not inputs:
        print("fake rawtherapee: missing -o or -c", file=sys.stderr)
        return 2
    if "FAKE_RT_FAIL" in (pp3.read_text() if pp3 and pp3.exists() else ""):
        print("fake rawtherapee: forced failure", file=sys.stderr)
        return 1

    lcp_enabled = False
    if pp3 is not None and pp3.exists():
        text = pp3.read_text(encoding="utf-8")
        lcp_enabled = "LcMode=lcp" in text

    out_dir.mkdir(parents=True, exist_ok=True)
    for src in inputs:
        with Image.open(src) as im:
            im = im.convert("RGB")
            if lcp_enabled:
                im = ImageOps.invert(im)
            target = out_dir / f"{src.stem}.jpg"
            im.save(target, "JPEG", quality=quality)
            print(f"fake rawtherapee: wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
