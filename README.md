# image-processing-prototype

Python prototype for image analysis and processing. The user picks a processing
mode in the browser, uploads an image, the backend processes it, and the result
is shown on top of the original with zoom, pan, a hide toggle and download.

Modes:

- **Lens correction** with Adobe LCP profiles (distortion and vignetting),
  rendered by RawTherapee. 110 iPhone profiles ship in `LCP/`.
- **Bead analysis** with OpenCV: finds the round dish, counts beads, measures
  each diameter in px and mm (manual mm/px scale), groups them into a size
  histogram, draws a numbered overlay and exports CSV. Can run lens correction
  first.
- **Beads via Cellpose 3 + circle fit**: same task and report, but a Cellpose 3
  neural network (cyto3, CPU) segments the beads and a least-squares circle is
  fitted to each one. Slower (tens of seconds for a 12 MP photo) and better on
  dense piles.

The interface is available in English (default) and Russian; the switch is in
the top-left corner and the choice is remembered in the browser.

## Run with Docker

```bash
docker build -t image-processing-prototype .
```

```bash
docker run --rm -p 8000:8000 image-processing-prototype
```

Open http://localhost:8000. API docs are at http://localhost:8000/api/docs,
health at http://localhost:8000/api/health.

For development with live reload:

```bash
docker compose up --build
```

## Configuration (environment variables)

| Variable          | Default            | Meaning                                   |
|-------------------|--------------------|-------------------------------------------|
| `LCP_DIR`         | `./LCP`            | directory with `.lcp` profiles            |
| `DATA_DIR`        | `./.data`          | uploads and results (temporary)           |
| `RAWTHERAPEE_CLI` | `rawtherapee-cli`  | command to run RawTherapee                |
| `PROCESS_TIMEOUT` | `300`              | seconds before a render is killed         |
| `RESULT_TTL`      | `3600`             | seconds to keep uploads and results       |
| `MAX_UPLOAD_MB`   | `200`              | upload size limit                         |
| `JPEG_QUALITY`    | `95`               | quality of the processed JPEG             |
| `PORT`            | `8000`             | HTTP port (Docker image only)             |

## Run without Docker

RawTherapee must be installed on the host (`rawtherapee-cli` on PATH), or
processing will fail with a clear error while the UI still loads.

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
```

```bash
.venv/bin/uvicorn app.main:app --reload --reload-dir src
```

## Tests

Tests use a fake `rawtherapee-cli` and synthetic images, so they run without
RawTherapee or Docker.

```bash
.venv/bin/pytest
```

## Layout

```
src/app/
  main.py           FastAPI app: API + UI in one process
  config.py         settings from environment variables
  api/              routes and temporary file storage
  processing/       LCP parser, RawTherapee wrapper, bead detection, circle fit, mode registry
  processing/modes/ one module per processing mode
  ui/               Jinja2 template and static JS/CSS
tests/
LCP/                Adobe lens profiles (read-only data)
```

## Adding a processing mode

1. Create `src/app/processing/modes/<name>.py` with a class exposing `id`,
   `name`, `description`, `params()` and `process()` (see `base.py`).
2. Register it in `build_registry()` in `src/app/processing/modes/__init__.py`.
3. The API and the UI pick it up without further changes.
