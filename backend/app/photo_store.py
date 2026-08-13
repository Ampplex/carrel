"""Local copies of uploaded photos.

Reeve retains the original image server-side — that is what makes it possible to
re-read a photo months later for a question nobody anticipated — but it exposes
no client-facing "fetch image by id" call. So the app keeps its own copy, for
two things it cannot otherwise do:

  * render thumbnails in the photo wall, and
  * re-attach the bytes when the user asks a question about a specific photo,
    which is the deterministic route to the vision model.

This is a display and convenience cache, not the system of record. Deleting
`var/photos/` loses the wall, not the memories.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from pydantic import BaseModel

from app.config import settings

_INDEX = settings.var_dir / "photos.json"
_lock = threading.Lock()

_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


class StoredPhoto(BaseModel):
    photo_id: str
    caption: str
    media_type: str
    filename: str
    stored_at: float

    @property
    def path(self) -> Path:
        return settings.photo_dir / self.filename


def _read_index() -> dict[str, dict]:
    if _INDEX.exists():
        try:
            return json.loads(_INDEX.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _write_index(data: dict[str, dict]) -> None:
    settings.var_dir.mkdir(parents=True, exist_ok=True)
    _INDEX.write_text(json.dumps(data, indent=2))


def save(raw: bytes, caption: str, media_type: str) -> StoredPhoto:
    photo_id = uuid.uuid4().hex
    filename = f"{photo_id}{_EXTENSIONS.get(media_type, '.bin')}"
    settings.photo_dir.mkdir(parents=True, exist_ok=True)
    (settings.photo_dir / filename).write_bytes(raw)

    photo = StoredPhoto(
        photo_id=photo_id,
        caption=caption,
        media_type=media_type,
        filename=filename,
        stored_at=time.time(),
    )
    with _lock:
        index = _read_index()
        index[photo_id] = photo.model_dump()
        _write_index(index)
    return photo


def get(photo_id: str) -> StoredPhoto | None:
    with _lock:
        entry = _read_index().get(photo_id)
    return StoredPhoto(**entry) if entry else None


def list_all() -> list[StoredPhoto]:
    with _lock:
        index = _read_index()
    photos = [StoredPhoto(**entry) for entry in index.values()]
    return sorted(photos, key=lambda p: p.stored_at, reverse=True)
