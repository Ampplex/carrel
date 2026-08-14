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
    # Which account owns this. Records written before accounts existed have
    # none, and are treated as belonging to nobody — see `_owned_by`.
    namespace: str = ""

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


def _owned_by(photo: StoredPhoto, namespace: str) -> bool:
    """Fail closed.

    A record with no namespace predates accounts and cannot be attributed to
    anyone, so nobody may read it. The alternative — treating unowned photos as
    public — is how a cache quietly becomes a leak.
    """
    return bool(photo.namespace) and photo.namespace == namespace


def save(raw: bytes, caption: str, media_type: str, namespace: str) -> StoredPhoto:
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
        namespace=namespace,
    )
    with _lock:
        index = _read_index()
        index[photo_id] = photo.model_dump()
        _write_index(index)
    return photo


def get(photo_id: str, namespace: str) -> StoredPhoto | None:
    """Look up a photo, but only within the caller's own account."""
    with _lock:
        entry = _read_index().get(photo_id)
    if not entry:
        return None
    photo = StoredPhoto(**entry)
    return photo if _owned_by(photo, namespace) else None


def list_for(namespace: str) -> list[StoredPhoto]:
    with _lock:
        index = _read_index()
    photos = [StoredPhoto(**e) for e in index.values()]
    return sorted(
        (p for p in photos if _owned_by(p, namespace)),
        key=lambda p: p.stored_at,
        reverse=True,
    )


def delete_for(namespace: str) -> int:
    """Remove every photo belonging to one account, files included.

    Used by account erasure. Deleting the index row without the file would leave
    the bytes on disk after someone asked for them to be gone.
    """
    removed = 0
    with _lock:
        index = _read_index()
        keep: dict[str, dict] = {}
        for photo_id, entry in index.items():
            photo = StoredPhoto(**entry)
            if _owned_by(photo, namespace):
                try:
                    photo.path.unlink(missing_ok=True)
                except OSError:
                    pass
                removed += 1
            else:
                keep[photo_id] = entry
        _write_index(keep)
    return removed
