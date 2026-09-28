# Image processing prototype: FastAPI app + RawTherapee CLI.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# rawtherapee (Debian bookworm ships 5.9) provides /usr/bin/rawtherapee-cli.
# It pulls GTK as a dependency; the CLI itself runs without a display.
# libglib2.0-0 is required by opencv-python-headless (libgthread); GTK already
# brings it in, but it is listed explicitly so removing rawtherapee never breaks cv2.
RUN apt-get update \
    && apt-get install -y --no-install-recommends rawtherapee libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch from the PyTorch index: the default PyPI wheel on x86_64 bundles
# CUDA and adds gigabytes. "==2.14.0" in pyproject accepts the "+cpu" local version.
RUN pip install "torch==2.14.0" --index-url https://download.pytorch.org/whl/cpu

# Install the package first so source edits do not invalidate the dependency layer.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

# Cellpose 3: keep model weights inside the image (no download at runtime) and
# warm numba's JIT cache so the first request does not pay ~20 s of compilation.
ENV CELLPOSE_LOCAL_MODELS_PATH=/app/models \
    NUMBA_CACHE_DIR=/app/.numba
RUN python -c "from cellpose import models; models.CellposeModel(gpu=False, model_type='cyto3')" \
    && ls -la /app/models

COPY LCP ./LCP

ENV LCP_DIR=/app/LCP \
    DATA_DIR=/data \
    RAWTHERAPEE_CLI=rawtherapee-cli \
    PORT=8000

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
