# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository.

## Project purpose

`image-processing-prototype` is a Python application for image analysis and
processing. The core user flow is:

1. The user opens the UI and picks a processing type / mode.
2. The user uploads an image.
3. The backend runs the selected processing pipeline.
4. The user views the result in the UI.

Processing modes are added incrementally as the project grows. Current modes:

- `lens_correction`: distortion and vignetting correction with Adobe LCP
  profiles, rendered by RawTherapee.
- `bead_analysis`: counts and sizes beads in a round dish with OpenCV
  (threshold, marker-controlled watershed, contour measures), reports a size
  histogram and a table, draws a numbered overlay, exports CSV. Scale mm/px is
  a user parameter; the mode can optionally run lens correction first.
- `cellpose_beads`: same task and report as `bead_analysis`, different
  algorithm: Cellpose 3 (cyto3 by default, CPU) segments the beads, then a
  least-squares circle is fitted to each mask outline (`circles.py`); the
  fitted diameter is the size and the relative RMS residual filters non-round
  objects. Registered only when `cellpose` is importable.

Bead modes share `bead_common.py` (parameters, RAW/LCP input preparation,
dish lookup, report/CSV/overlay assembly). A new bead algorithm should only
produce a `list[Bead]` and call `bead_common.build_result`.

Design every layer so that adding a new mode does not require touching
existing modes.

The project is 100% Python. Do not introduce a second language for
application code.

## Non-negotiable: Docker

The project must build and run as a Docker image. Every change must keep
`docker build` and `docker run` working. Concretely:

- Keep a `Dockerfile` at the repository root. Prefer a slim official Python
  base image and a multi-stage build if native image libraries need compilers.
- All runtime configuration comes from environment variables with sane
  defaults, so the container runs with no flags beyond a port mapping.
- Expose one HTTP port. The UI and API are served from the same container.
- Provide a `docker-compose.yml` (or `compose.yaml`) for local development
  with a volume mount for `src/` and a mount for the `LCP/` directory.
- Do not depend on anything installed on the host. If a system library is
  required (for example libGL for OpenCV), install it in the Dockerfile and
  document why.
- Before finishing any task that touches dependencies, the Dockerfile, or the
  entry point, run the build and start the container:

  ```bash
  docker build -t image-processing-prototype .
  ```

  ```bash
  docker run --rm -p 8000:8000 image-processing-prototype
  ```

  Then confirm the health endpoint and the UI respond. Report failures
  verbatim.

## Architecture

Three layers, kept in separate packages so each can be tested alone:

- **UI.** Web interface for choosing a mode, uploading an image, and viewing
  the result. It talks to the backend only through the API.
- **API.** HTTP layer. Lists available processing modes, accepts uploads,
  dispatches to the processing layer, returns results. Thin: no image math
  here.
- **Processing.** Pure processing logic using image libraries (for example
  Pillow, OpenCV, NumPy, scikit-image). Each processing mode is a
  self-contained module that registers itself with a common interface
  (name, description, parameters, `process(image, params) -> result`).
  Adding a mode means adding one module and, at most, one registration line.

Rules across layers:

- Processing functions take and return in-memory images or arrays and never
  read from the request or write to the response directly.
- Mode discovery is data-driven. The UI must render whatever the API
  reports, not a hardcoded list.
- Keep heavy libraries imported inside the modes that need them, so a broken
  optional dependency disables one mode rather than the whole app.
- Uploaded files are stored temporarily and cleaned up. Never commit sample
  uploads or results.

## Repository layout

```
.
├── AGENTS.md
├── README.md            # run and test commands
├── Dockerfile           # python:3.12-slim-bookworm + rawtherapee from apt
├── docker-compose.yml   # dev: mounts src/ and LCP/, live reload
├── pyproject.toml       # single dependency manifest, pinned versions, src layout
├── src/app/
│   ├── main.py          # create_app(): FastAPI serving API + UI, static cache busting
│   ├── config.py        # Settings dataclass, every value from an env var
│   ├── i18n.py          # t()/tr() bilingual text helpers
│   ├── api/
│   │   ├── routes.py    # /api/health, /api/modes, /api/profiles, /api/uploads…
│   │   └── storage.py   # ItemStore: <DATA_DIR>/items/<uuid>/, TTL cleanup
│   ├── processing/
│   │   ├── base.py      # ParamSpec, ProcessRequest, ProcessResult, ExtraFile, ProcessingMode
│   │   ├── registry.py  # Registry of modes
│   │   ├── lcp.py       # LCP parser + LcpIndex (suggest by EXIF lens name)
│   │   ├── rawtherapee.py  # pp3 generation + rawtherapee-cli runner
│   │   ├── exif.py      # exifread wrapper, supported extensions
│   │   ├── beads.py     # pure OpenCV functions: detect_dish, segment_beads, histogram, overlay
│   │   ├── circles.py   # least-squares circle fit, label masks -> beads
│   │   ├── bead_common.py  # shared params / input prep / report for bead modes
│   │   └── modes/       # one module per mode; build_registry() wires them
│   │       ├── lens_correction.py
│   │       ├── bead_analysis.py
│   │       └── cellpose_beads.py
│   └── ui/
│       ├── templates/index.html
│       └── static/app.js, style.css   # vanilla JS: form, upload, overlay viewer
├── tests/               # pytest; fake_rawtherapee.py stands in for the real CLI
└── LCP/                 # 110 Adobe .lcp lens profiles, iPhone 14 through 17e
```

All source code lives under `src/`. Do not put application modules, scripts,
or packages at the repository root or anywhere else. Use the standard
`src` layout: the package is installed (editable in development, regular in
the Docker image) and imported as `app.…`, never via `sys.path` hacks. Tests
stay in `tests/` outside `src/` and import the installed package.

### Languages

The UI is bilingual (English default, Russian). Static UI strings live in the
`I18N` table in `app.js`; everything that comes from the backend (mode names,
descriptions, parameter labels and help, notes, report labels, error messages)
is written with `t("English", "Русский")` from `app/i18n.py` and resolved with
`tr(text, lang)`. The language reaches the API as `?lang=` (or
`Accept-Language`) on reads and as `lang` in the process body; modes get it in
`ProcessRequest.lang`. When adding a mode or a message, always provide both
languages; never hardcode one.

### How a request flows

1. `POST /api/uploads` stores the file, reads EXIF, suggests an LCP profile.
2. `POST /api/uploads/{id}/process` with `{mode, params}` calls
   `mode.process(ProcessRequest)`; the mode writes `processed.jpg` (and
   `original.jpg` for formats the browser cannot show, such as TIFF/DNG).
3. `GET /api/uploads/{id}/files/{original|processed}?download=1` serves them.

### Adding a processing mode

Create `src/app/processing/modes/<name>.py` with a class exposing `id`,
`name`, `description`, `params()` and `process()`, then register it in
`build_registry()` inside `src/app/processing/modes/__init__.py`, wrapped in
its own try/except like the existing ones. The UI renders `params()` from the
`ParamSpec` types `select`, `bool`, `number`, grouped by `section`; extend
`app.js` only if a new type is needed.

A mode returns a `ProcessResult`. Beyond the overlay image it can carry:

- `info["notes"]`: list of strings shown under the result.
- `info["report"]`: `{"stats": [{label, value}], "histogram": {title, unit,
  bins: [{lo, hi, count, percent}]}, "tables": [{title, columns, rows}]}`.
  The UI renders this generically (stat tiles, one-series bar histogram with
  hover tooltip, collapsible tables). Put numbers here, not in `log`.
- `files`: list of `ExtraFile` (CSV, JSON...). The API copies them into
  `<item>/extra/` and serves them at `/api/uploads/{id}/files/{name}?download=1`.

Keep image math in a pure module next to `beads.py` (arrays in, arrays out)
and let the mode module do only parameter parsing, file handling and report
assembly.

### Cellpose / torch notes

- `torch` is installed from the PyTorch CPU index in the Dockerfile before
  `pip install .`; the `==2.14.0` pin in `pyproject.toml` accepts the `+cpu`
  build. Never let the default PyPI torch (with CUDA) into the image.
- `cyto3` weights are downloaded at build time into
  `CELLPOSE_LOCAL_MODELS_PATH=/app/models`, and `NUMBA_CACHE_DIR=/app/.numba`
  is warmed by importing cellpose during the build. The container must not
  need internet at runtime.
- `cellpose` is imported lazily inside the mode; app startup must stay fast.
  The model object is cached per (model_type, gpu).
- `numpy` is pinned to what cellpose 3.1 accepts (2.0.x). Bump both together.
- CPU throughput is roughly 6 s per megapixel; the mode crops to the dish and
  offers a `downscale` parameter.

### RawTherapee notes

- The wrapper writes a partial `.pp3` with only the `[LensProfile]` section
  and runs `rawtherapee-cli -o <dir> -p <pp3> -a -j95 -js3 -Y -c <input>`.
  Output lands at `<dir>/<input stem>.jpg`. `-a` is required: without it the
  CLI silently skips extensions missing from its options file (PNG).
  The output directory must exist before the call.
- Distortion and vignetting from an LCP work for JPEG/TIFF/PNG and DNG.
  LCP chromatic-aberration correction in RawTherapee applies to raw files
  only, and the bundled profiles have no CA model anyway.
- Debian bookworm's `rawtherapee` package is 5.9 and includes the CLI.

## The LCP data

- **Format.** Each `.lcp` file is XMP/RDF XML. The root is `x:xmpmeta`, and
  profiles live under `photoshop:CameraProfiles` as an `rdf:Seq` of
  `rdf:Description` elements in the `stCamera` namespace
  (`http://ns.adobe.com/photoshop/1.0/camera-profile`). Parse with a real XML
  parser; do not regex the files.
- **Naming.** `Apple iPhone (Apple iPhone <model> <back|front> camera <focal>mm f<aperture>[ - LRM]) [- RAW].lcp`.
  Filenames contain spaces and parentheses. Always quote paths in shell commands.
- **RAW pairs.** 55 files carry a `- RAW` suffix. They are byte-for-byte
  identical to their non-RAW twin except `stCamera:CameraRawProfile="True"`.
  Pick a profile by the `CameraRawProfile` flag, not by filename.
- **Multiple profiles per file.** Most files hold one profile. The four
  `- LRM` files hold two profiles each. Iterate the `rdf:Seq`; never assume a
  single entry.
- **Per-profile identity fields.** `Make`, `Model`, `Lens`, `LensPrettyName`,
  `ProfileName`, `ImageWidth`, `ImageLength`, `FocalLength`, `ApertureValue`,
  `FocusDistance`, `SensorFormatFactor`. Some profiles add `LensInfo`,
  `UniqueCameraModel`, and an `AlternateLensNames` list. Match a camera by
  `Lens` and fall back to `AlternateLensNames`.
- **Correction models.** Every profile has a `PerspectiveModel` (Version 2)
  with `FocalLengthX`, `FocalLengthY`, `RadialDistortParam1..3`, and usually
  `ImageXCenter`, `ImageYCenter`, `ResidualMeanError`,
  `ResidualStandardDeviation`. Only 4 profiles include a `VignetteModel`
  (`VignetteModelParam1..3`). None include a chromatic-aberration model.
  Treat every model block and every parameter as optional. Two profiles lack
  `RadialDistortParam3`, and 18 lack the image-center fields; default the
  center to the image midpoint in that case.
- **Units.** `FocalLengthX/Y` and the distortion parameters follow the Adobe
  LCP convention: normalized by the sensor's longer dimension and expressed
  relative to the image center. Verify against Adobe's LCP specification
  before implementing the undistortion math, and add a unit test with one
  known profile.

Treat the `LCP/` directory as read-only input data. Do not reformat, rename,
or regenerate these files. If a derived index (JSON, SQLite, etc.) is needed,
generate it into a separate directory and add the generator script to the repo.

## Python conventions

- One dependency manifest (`pyproject.toml`) at the root, versions pinned,
  with the package discovered from `src/` (`[tool.setuptools.packages.find]
  where = ["src"]` or the equivalent for the chosen build backend). Keep a
  lock file if the chosen tool produces one, and use the same install
  command in the Dockerfile and in the README.
- Type hints on public functions. Pure functions for image math so they are
  testable without a running server.
- Tests live in `tests/` and run with `pytest`. Each processing mode gets at
  least one test with a small synthetic image; do not commit real photos.
- Add a `.gitignore` for Python (`__pycache__`, virtualenvs, build output,
  uploaded files, results) before the first commit that would produce them.
- Sample images and large binaries stay outside git or under Git LFS. The LCP
  files are small (about 440 KB total) and stay in git.
- Do not commit secrets, API keys, or personal photos.

## Git workflow

- Default branch is `main`. Commit messages are short imperative sentences,
  like the existing `Add LCP`.
- Do not commit or push unless asked. Do not rewrite history on `main`.
- When an agent creates a commit, end the message with the attribution line
  the session provides.

## Verification checklist for changes

1. `docker build` succeeds and the container starts and serves the UI.
2. `pytest` passes inside the container or in the project virtualenv.
3. If you add a parser for LCP, run it over all 110 files and assert that 114
   profiles are found, 55 with `CameraRawProfile="True"`.
4. If you add correction math, test it on one profile with and without
   `ImageXCenter`/`ImageYCenter`.
5. If you add a processing mode, confirm it appears in the API mode list and
   in the UI without any UI code change.
6. For `bead_analysis`, `tests/synthetic.py` generates a dish with beads of
   known sizes; detection must find every bead and measure diameters within
   15 % for both marker methods.
7. `tests/test_cellpose_mode.py` runs the real network on a small synthetic
   image (skipped when cellpose is missing). Keep it under ~10 s.
