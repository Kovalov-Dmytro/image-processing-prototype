"""Temporary on-disk storage for uploads and results.

Layout: <data_dir>/items/<uuid>/
    input.<ext>     the uploaded file
    meta.json       metadata written by the API
    processed.jpg   result (written by the mode into work_dir)
    original.jpg    optional "before" render for non-browser formats
    after/, before/ RawTherapee work directories

Items older than the TTL are removed on every new upload.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

_ID_ALPHABET = set("0123456789abcdef")


class UploadTooLarge(Exception):
    pass


@dataclass
class Item:
    id: str
    dir: Path

    @property
    def meta_path(self) -> Path:
        return self.dir / "meta.json"

    def read_meta(self) -> dict:
        if not self.meta_path.exists():
            return {}
        return json.loads(self.meta_path.read_text(encoding="utf-8"))

    def write_meta(self, meta: dict) -> None:
        self.meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def update_meta(self, **fields) -> dict:
        meta = self.read_meta()
        meta.update(fields)
        self.write_meta(meta)
        return meta

    @property
    def input_path(self) -> Path | None:
        for candidate in self.dir.glob("input.*"):
            return candidate
        return None


class ItemStore:
    def __init__(self, data_dir: Path, ttl_seconds: int, max_bytes: int) -> None:
        self._root = data_dir / "items"
        self._root.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl_seconds
        self._max_bytes = max_bytes

    @property
    def root(self) -> Path:
        return self._root

    def cleanup(self) -> int:
        """Delete items older than the TTL. Returns how many were removed."""
        now = time.time()
        removed = 0
        for item_dir in self._root.iterdir():
            if not item_dir.is_dir():
                continue
            try:
                age = now - item_dir.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > self._ttl:
                shutil.rmtree(item_dir, ignore_errors=True)
                removed += 1
        return removed

    def create(self, original_filename: str, extension: str, stream: BinaryIO) -> Item:
        """Store an upload. extension includes the leading dot and is already validated."""
        self.cleanup()
        item_id = uuid.uuid4().hex
        item_dir = self._root / item_id
        item_dir.mkdir(parents=True)
        target = item_dir / f"input{extension}"
        written = 0
        with target.open("wb") as out:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > self._max_bytes:
                    out.close()
                    shutil.rmtree(item_dir, ignore_errors=True)
                    raise UploadTooLarge()
                out.write(chunk)
        item = Item(id=item_id, dir=item_dir)
        item.write_meta(
            {
                "id": item_id,
                "filename": original_filename,
                "extension": extension,
                "size": written,
                "created": time.time(),
            }
        )
        return item

    def get(self, item_id: str) -> Item | None:
        if not item_id or len(item_id) != 32 or set(item_id) - _ID_ALPHABET:
            return None
        item_dir = self._root / item_id
        if not item_dir.is_dir():
            return None
        return Item(id=item_id, dir=item_dir)
