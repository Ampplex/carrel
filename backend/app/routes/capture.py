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
import binascii
import time
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app import auth, photo_store, reeve_gateway
from app.chunking import chunk_note
from app.config import settings
from app.models import NoteIn, PhotoAccepted, PhotoBase64In, WriteAccepted
from app.pending import registry

router = APIRouter()


@router.post("/api/notes", response_model=WriteAccepted)
def create_note(payload: NoteIn, user: dict = Depends(auth.current_user)) -> WriteAccepted:
    ns = user["namespace"]
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
        result = reeve_gateway.store_note(chunk, ns)
        accepted.append(
            registry.add(namespace=ns, kind="note", preview=chunk, batch_id=batch_id, store_result=result)
        )

    return WriteAccepted(batch_id=batch_id, pending=accepted, chunked=len(chunks) > 1)


def _store_photo_bytes(raw: bytes, media_type: str, caption: str, ns: str) -> PhotoAccepted:
    """Shared by both upload routes. Validates, keeps a local copy, and sends
    the bytes on to Reeve as one memory (caption fused with what the vision
    model sees)."""
    if media_type not in settings.allowed_media_types:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported image type '{media_type}'. "
            f"Allowed: {', '.join(sorted(settings.allowed_media_types))}.",
        )
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload.")
    if len(raw) > settings.max_image_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Image is {len(raw) // 1024} KB; the limit is "
            f"{settings.max_image_bytes // 1024} KB.",
        )

    photo = photo_store.save(raw, caption, media_type, ns)
    encoded = base64.b64encode(raw).decode("ascii")

    result = reeve_gateway.store_photo(caption, encoded, media_type, ns)
    batch_id = uuid.uuid4().hex
    accepted = registry.add(namespace=ns, kind="photo", preview=caption, batch_id=batch_id, store_result=result)

    return PhotoAccepted(
        batch_id=batch_id,
        pending=[accepted],
        photo_id=photo.photo_id,
        thumb_url=f"/api/photos/{photo.photo_id}/raw",
    )


@router.post("/api/photos", response_model=PhotoAccepted)
async def create_photo(
    file: UploadFile = File(...),
    caption: str = Form(...),
    user: dict = Depends(auth.current_user),
) -> PhotoAccepted:
    """Multipart upload — what a browser sends."""
    raw = await file.read()
    return await run_in_threadpool(
        _store_photo_bytes,
        raw,
        (file.content_type or "").lower(),
        caption,
        user["namespace"],
    )


@router.post("/api/photos/base64", response_model=PhotoAccepted)
async def create_photo_base64(
    payload: PhotoBase64In,
    user: dict = Depends(auth.current_user),
) -> PhotoAccepted:
    """Base64 upload — what React Native sends.

    Not redundant with the multipart route: React Native 0.86 tightened its
    FormData validation and rejects the `{uri, name, type}` object that every
    RN upload example still uses, with `Unsupported FormDataPart implementation`.
    Working around that on the client means either constructing a real Blob (RN's
    Blob support has its own gaps) or reading the file and sending it as JSON.

    JSON is the honest option here, because the bytes end up base64-encoded
    anyway — Reeve's API takes `image_base64`, so multipart was only ever a
    detour through a different encoding and back.

    Costs roughly a third more bytes on the wire than multipart. For single
    phone photos under the 4 MB cap that is a fair trade for an upload path that
    does not depend on framework internals.
    """
    try:
        raw = base64.b64decode(payload.image_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Image data is not valid base64.") from exc

    return await run_in_threadpool(
        _store_photo_bytes,
        raw,
        payload.media_type.lower(),
        payload.caption,
        user["namespace"],
    )
