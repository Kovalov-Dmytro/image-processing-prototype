# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository.

## Project purpose

`image-processing-prototype` is a Python application for image analysis and
processing. The core user flow is:

1. The user opens the UI and picks a processing type / mode.
2. The user uploads an image.
3. The backend runs the selected processing pipeline.
4. The user views the result in the UI.

Processing modes are added incrementally as the project grows. The first
mode is lens correction based on Adobe LCP profiles (see below). Design every
layer so that adding a new mode does not require touching existing modes.

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

Current state:

```
.
├── AGENTS.md          # this file
└── LCP/               # 110 Adobe .lcp lens profiles, iPhone 14 through 17e
```

Target layout once code lands (adjust names to match what actually exists;
check the tree before assuming):

```
.
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml     # single dependency manifest, with pinned versions
├── README.md          # run and test commands
├── src/
│   └── app/           # the only Python package; everything importable lives here
│       ├── api/       # HTTP routes, schemas
│       ├── ui/        # templates / static assets or frontend served by the app
│       ├── processing/# one module per mode + registry
│       └── main.py    # entry point
├── tests/
└── LCP/
```

All source code lives under `src/`. Do not put application modules, scripts,
or packages at the repository root or anywhere else. Use the standard
`src` layout: the package is installed (editable in development, regular in
the Docker image) and imported as `app.…`, never via `sys.path` hacks. Tests
stay in `tests/` outside `src/` and import the installed package.

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
