"""Application entry point: builds the FastAPI app that serves both the API and the UI."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import router as api_router
from app.api.storage import ItemStore
from app.config import Settings
from app.processing.modes import build_registry
from app.processing.rawtherapee import RawTherapee

UI_DIR = Path(__file__).parent / "ui"


def _static_version() -> str:
    """Short hash of the static files' contents, used as a cache-busting query string."""
    digest = hashlib.sha1()
    for path in sorted((UI_DIR / "static").glob("*")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = settings or Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    registry = build_registry(settings)
    lens_mode = registry.get("lens_correction")

    app = FastAPI(title="Image processing prototype", docs_url="/api/docs", redoc_url=None)
    app.state.settings = settings
    app.state.registry = registry
    app.state.store = ItemStore(
        settings.data_dir, ttl_seconds=settings.result_ttl, max_bytes=settings.max_upload_bytes
    )
    app.state.rawtherapee = RawTherapee(settings.rawtherapee_cli, timeout=settings.process_timeout)
    app.state.lcp_index = getattr(lens_mode, "index", None)

    app.include_router(api_router)
    app.mount("/static", NoCacheStaticFiles(directory=UI_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=UI_DIR / "templates")
    static_version = _static_version()

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index(request: Request) -> HTMLResponse:
        response = templates.TemplateResponse(
            request, "index.html", {"request": request, "static_version": static_version}
        )
        response.headers["Cache-Control"] = "no-cache"
        return response

    return app


app = create_app()
