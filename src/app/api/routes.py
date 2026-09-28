"""API routes."""

from __future__ import annotations

import importlib.util
import logging
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.api.storage import Item, ItemStore, UploadTooLarge
from app.i18n import DEFAULT_LANG, normalize_lang, t, tr
from app.processing.base import ProcessingError, ProcessRequest
from app.processing.exif import (
    SUPPORTED_EXTENSIONS,
    is_browser_viewable,
    is_raw,
    read_meta,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


class ProcessBody(BaseModel):
    mode: str
    params: dict[str, Any] = Field(default_factory=dict)
    lang: str = DEFAULT_LANG


def _store(request: Request) -> ItemStore:
    return request.app.state.store


def _lang(request: Request, explicit: str | None = None) -> str:
    return normalize_lang(explicit or request.query_params.get("lang") or request.headers.get("accept-language"))


def _item_or_404(request: Request, item_id: str) -> Item:
    item = _store(request).get(item_id)
    if item is None or item.input_path is None:
        raise HTTPException(
            status_code=404,
            detail=tr(t("Upload not found or expired.", "Загрузка не найдена или устарела."), _lang(request)),
        )
    return item


def _file_url(item_id: str, name: str, download: bool = False) -> str:
    url = f"/api/uploads/{item_id}/files/{name}"
    return url + "?download=1" if download else url


def _original_url(item: Item) -> str | None:
    if (item.dir / "original.jpg").exists():
        return _file_url(item.id, "original")
    input_path = item.input_path
    if input_path is not None and is_browser_viewable(input_path):
        return _file_url(item.id, "original")
    return None


@router.get("/health")
def health(request: Request) -> dict:
    rt = request.app.state.rawtherapee
    index = request.app.state.lcp_index
    return {
        "status": "ok",
        "rawtherapee": rt.is_available(),
        "rawtherapee_cli": rt.executable,
        "cellpose": importlib.util.find_spec("cellpose") is not None,
        "modes": [m.id for m in request.app.state.registry.list()],
        "lcp_files": len(index) if index is not None else 0,
        "lcp_profiles": index.profile_count if index is not None else 0,
    }


@router.get("/modes")
def list_modes(request: Request) -> list[dict]:
    return request.app.state.registry.to_dict(_lang(request))


@router.get("/profiles")
def list_profiles(request: Request) -> list[dict]:
    index = request.app.state.lcp_index
    if index is None:
        return []
    return [f.to_dict() for f in index.files]


@router.post("/uploads")
def create_upload(request: Request, file: UploadFile = File(...)) -> dict:
    lang = _lang(request)
    filename = file.filename or "image"
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        formats = ", ".join(sorted(e.lstrip(".").upper() for e in SUPPORTED_EXTENSIONS))
        raise HTTPException(
            status_code=422,
            detail=tr(t(f"Only {formats} are supported.", f"Поддерживаются только {formats}."), lang),
        )
    try:
        item = _store(request).create(filename, extension, file.file)
    except UploadTooLarge:
        mb = request.app.state.settings.max_upload_mb
        raise HTTPException(
            status_code=413,
            detail=tr(t(f"File is larger than {mb} MB.", f"Файл больше {mb} МБ."), lang),
        ) from None

    input_path = item.input_path
    assert input_path is not None
    meta = read_meta(input_path)
    raw = is_raw(input_path)
    index = request.app.state.lcp_index
    suggested = index.suggest(meta.lens_model, camera_raw=raw) if index is not None else None

    item.update_meta(
        exif=meta.to_dict(),
        camera_raw=raw,
        suggested_profile=suggested.id if suggested else None,
    )
    return {
        "id": item.id,
        "filename": filename,
        "extension": extension,
        "size": item.read_meta().get("size"),
        "camera_raw": raw,
        "browser_viewable": is_browser_viewable(input_path),
        "meta": meta.to_dict(),
        "suggested_profile": suggested.id if suggested else None,
        "original_url": _original_url(item),
    }


@router.post("/uploads/{item_id}/process")
def process_upload(request: Request, item_id: str, body: ProcessBody) -> dict:
    item = _item_or_404(request, item_id)
    lang = _lang(request, body.lang)
    mode = request.app.state.registry.get(body.mode)
    if mode is None:
        raise HTTPException(
            status_code=404,
            detail=tr(t(f"Mode not found: {body.mode}", f"Режим не найден: {body.mode}"), lang),
        )
    input_path = item.input_path
    assert input_path is not None

    try:
        result = mode.process(
            ProcessRequest(input_path=input_path, work_dir=item.dir, params=body.params, lang=lang)
        )
    except ProcessingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - report unexpected failures to the UI
        log.exception("mode %s failed for item %s", body.mode, item_id)
        raise HTTPException(
            status_code=500,
            detail=tr(t(f"Processing failed: {exc}", f"Ошибка обработки: {exc}"), lang),
        ) from exc

    # Normalize result file names so the file endpoint can find them.
    processed_target = item.dir / "processed.jpg"
    if result.processed_path.resolve() != processed_target.resolve():
        result.processed_path.replace(processed_target)
    if result.original_path is not None:
        original_target = item.dir / "original.jpg"
        if result.original_path.resolve() != original_target.resolve():
            result.original_path.replace(original_target)

    extra_dir = item.dir / "extra"
    shutil.rmtree(extra_dir, ignore_errors=True)
    files_meta: dict[str, dict[str, str]] = {}
    files_out: list[dict[str, str]] = []
    for extra in result.files:
        if extra.name in {"original", "processed"} or "/" in extra.name or extra.name.startswith("."):
            raise HTTPException(status_code=500, detail=f"Invalid result file name: {extra.name}")
        extra_dir.mkdir(parents=True, exist_ok=True)
        target = extra_dir / extra.name
        if extra.path.resolve() != target.resolve():
            extra.path.replace(target)
        files_meta[extra.name] = {"label": extra.label, "media_type": extra.media_type}
        files_out.append({"name": extra.name, "label": extra.label, "url": _file_url(item.id, extra.name, download=True)})

    item.update_meta(mode=body.mode, params=body.params, info=result.info, files=files_meta)
    return {
        "id": item.id,
        "mode": body.mode,
        "original_url": _original_url(item),
        "processed_url": _file_url(item.id, "processed"),
        "download_url": _file_url(item.id, "processed", download=True),
        "download_original_url": _file_url(item.id, "original", download=True),
        "files": files_out,
        "log": result.log,
        "info": result.info,
    }


@router.get("/uploads/{item_id}/files/{name}")
def get_file(request: Request, item_id: str, name: str, download: bool = False) -> FileResponse:
    item = _item_or_404(request, item_id)
    meta = item.read_meta()
    stem = Path(meta.get("filename") or "image").stem

    if name == "processed":
        path = item.dir / "processed.jpg"
        media_type = "image/jpeg"
        download_name = f"{stem}_{meta.get('mode', 'processed')}.jpg"
    elif name == "original":
        rendered = item.dir / "original.jpg"
        input_path = item.input_path
        assert input_path is not None
        if download and input_path is not None:
            path = input_path
            media_type = None
            download_name = meta.get("filename") or input_path.name
        elif rendered.exists():
            path = rendered
            media_type = "image/jpeg"
            download_name = f"{stem}_original.jpg"
        elif is_browser_viewable(input_path):
            path = input_path
            media_type = "image/png" if input_path.suffix.lower() == ".png" else "image/jpeg"
            download_name = meta.get("filename") or input_path.name
        else:
            raise HTTPException(status_code=404, detail="Оригинал ещё не отрисован.")
    elif name in (meta.get("files") or {}):
        entry = meta["files"][name]
        path = item.dir / "extra" / name
        media_type = entry.get("media_type") or None
        download_name = f"{stem}_{name}"
    else:
        raise HTTPException(status_code=404, detail="Нет такого файла.")

    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл не найден.")
    headers = {"Cache-Control": "no-store"}
    return FileResponse(
        path,
        media_type=media_type,
        headers=headers,
        filename=download_name if download else None,
    )
