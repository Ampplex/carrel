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
import logging
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from app import auth, photo_store, reeve_gateway
from app.chunking import chunk_note
from app.config import settings
from app.models import NoteIn, PhotoAccepted, PhotoBase64In, WriteAccepted
from app.pending import registry

router = APIRouter()
log = logging.getLogger("carrel.capture")


@router.post("/api/notes", response_model=WriteAccepted)
def create_note(
    payload: NoteIn,
    background: BackgroundTasks,
    user: dict = Depends(auth.current_user),
) -> WriteAccepted:
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

    # Every chunk gets a tray entry before anything is sent, so the response can
    # come back immediately and the app can show what is in flight.
    accepted = [
        registry.add(namespace=ns, kind="note", preview=chunk, batch_id=batch_id, store_result=None)
        for chunk in chunks
    ]

    # The writing happens after the response.
    #
    # Writes are paced to avoid throttling upstream, so doing this inline meant
    # the request stayed open for roughly two seconds per chunk — twenty-four
    # seconds at the old twelve-chunk ceiling, and over two minutes at the
    # current one. That is what actually capped how much text could be stored;
    # the chunk count was only the symptom.
    #
    # The tray was built for exactly this: it already knows how to say "accepted,
    # still settling" and to stop claiming so when a write turns out to have
    # failed. Nothing new had to be invented to make the response instant.
    background.add_task(_write_chunks, ns, list(zip(chunks, [a.id for a in accepted])))

    return WriteAccepted(batch_id=batch_id, pending=accepted, chunked=len(chunks) > 1)


def _write_chunks(namespace: str, work: list[tuple[str, str]]) -> None:
    """Send each chunk to Reeve, pacing between them, recording what happened.

    A failure marks that chunk `failed` rather than leaving it `indexing`. An
    entry that sits there looking busy and then quietly ages out of the tray is
    the same silent loss this whole subsystem exists to prevent.
    """
    for index, (chunk, item_id) in enumerate(work):
        if index:
            time.sleep(settings.chunk_pace_seconds)
        try:
            result = reeve_gateway.store_note(chunk, namespace)
            registry.mark_written(namespace, item_id, failed=False, result=result)
        except Exception as exc:  # noqa: BLE001 - one bad chunk must not stop the rest
            log.warning("chunk %d/%d failed for %s: %s", index + 1, len(work), namespace, exc)
            registry.mark_written(namespace, item_id, failed=True)


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
