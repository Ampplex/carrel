"""Writing memories: notes and photos.

Both endpoints are cheap — writes do not count against the query quota — and
both return immediately with pending pointers rather than pretending the memory
is searchable yet.

Note the handler styles. The text endpoint is a plain `def`, so Starlette runs
it in its worker threadpool automatically; the SDK is synchronous and blocking,
and a forgotten `run_in_threadpool` inside an `async def` would stall the whole
event loop for as long as the call takes. The photo endpoint must be `async def`
because it awaits the upload, so it wraps every SDK call explicitly.
"""

from __future__ import annotations

import base64
import time
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app import photo_store, reeve_gateway
from app.chunking import chunk_note
from app.config import settings
from app.models import NoteIn, PhotoAccepted, WriteAccepted
from app.pending import registry

router = APIRouter()


@router.post("/api/notes", response_model=WriteAccepted)
def create_note(payload: NoteIn) -> WriteAccepted:
    chunks = chunk_note(payload.text, payload.context_line)
    if not chunks:
        raise HTTPException(status_code=400, detail="Note is empty.")
    if len(chunks) >= settings.max_chunks:
        raise HTTPException(
            status_code=413,
            detail=f"Note is too long; it would split into more than {settings.max_chunks} "
            "memories. Break it up yourself so the pieces stay meaningful.",
        )

    batch_id = uuid.uuid4().hex
    accepted = []
    for index, chunk in enumerate(chunks):
        if index:
            # Bursts of writes trigger model throttling upstream, and each chunk
            # costs a vision-free but still model-backed extraction.
            time.sleep(settings.chunk_pace_seconds)
        result = reeve_gateway.store_note(chunk)
        accepted.append(
            registry.add(kind="note", preview=chunk, batch_id=batch_id, store_result=result)
        )

    return WriteAccepted(batch_id=batch_id, pending=accepted, chunked=len(chunks) > 1)


@router.post("/api/photos", response_model=PhotoAccepted)
async def create_photo(
    file: UploadFile = File(...),
    caption: str = Form(...),
) -> PhotoAccepted:
    media_type = (file.content_type or "").lower()
    if media_type not in settings.allowed_media_types:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported image type '{media_type}'. "
            f"Allowed: {', '.join(sorted(settings.allowed_media_types))}.",
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload.")
    if len(raw) > settings.max_image_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Image is {len(raw) // 1024} KB; the limit is "
            f"{settings.max_image_bytes // 1024} KB.",
        )

    photo = photo_store.save(raw, caption, media_type)
    encoded = base64.b64encode(raw).decode("ascii")

    result = await run_in_threadpool(reeve_gateway.store_photo, caption, encoded, media_type)
    batch_id = uuid.uuid4().hex
    accepted = registry.add(
        kind="photo", preview=caption, batch_id=batch_id, store_result=result
    )

    return PhotoAccepted(
        batch_id=batch_id,
        pending=[accepted],
        photo_id=photo.photo_id,
        thumb_url=f"/api/photos/{photo.photo_id}/raw",
    )
