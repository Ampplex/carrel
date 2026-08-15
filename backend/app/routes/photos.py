"""Photo memory: the wall, re-interrogation, and search by appearance.

The interesting endpoint is `/api/photos/ask`. Reeve keeps the original image,
so a question can be answered by looking at the picture again at query time —
not by searching text that somebody wrote when they uploaded it. That is the
capability an embedding-only system cannot have: an embedding is a fingerprint,
useful for finding an image and useless for reading one.

Two routes to that answer, and the difference is worth showing side by side:

  * **attached** — the bytes are sent with the question, so the vision model is
    reached deterministically.
  * **lane** — nothing is attached, and the photo has to be selected by the
    image retrieval lane on its own merits. More impressive when it works, and
    it does not always: the lane is tuned to prefer precision over recall, and
    it stays silent entirely until the namespace holds at least three photos.
"""

from __future__ import annotations

import base64
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi import Response
from starlette.concurrency import run_in_threadpool

from app import auth, photo_store, quota, reeve_gateway
from app.config import settings
from app.models import PhotoAnswer, PhotoAskIn, PhotoBase64AskIn, PhotoOut, SearchIn

router = APIRouter()

# Below this many photos in the namespace, the image lane declines to rank at
# all, so unattached photo questions cannot work. Mirrors the server's setting.
IMAGE_LANE_MIN_SAMPLE = 3


@router.get("/api/photos", response_model=list[PhotoOut])
def list_photos(user: dict = Depends(auth.current_user)) -> list[PhotoOut]:
    return [
        PhotoOut(
            photo_id=p.photo_id,
            caption=p.caption,
            thumb_url=f"/api/photos/{p.photo_id}/raw",
            stored_at=p.stored_at,
        )
        for p in photo_store.list_for(user["namespace"])
    ]


@router.get("/api/photos/{photo_id}/raw")
def photo_raw(photo_id: str, user: dict = Depends(auth.current_user)) -> Response:
    """Bytes, streamed through this server rather than redirected to S3.

    A presigned URL would be one line and would also hand out a link that works
    for anyone who has it, for as long as it lives, with no account check. Going
    through the route keeps every read behind the same ownership test as
    everything else, at the cost of the bytes passing through here.
    """
    photo = photo_store.get(photo_id, user["namespace"])
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found.")
    try:
        raw = photo_store.read_bytes(photo)
    except Exception as exc:  # noqa: BLE001 - the object may be gone
        raise HTTPException(status_code=404, detail="Photo not found.") from exc
    return Response(
        content=raw,
        media_type=photo.media_type,
        # Private: this is one account's photograph and must never be held by a
        # shared cache on the way back.
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.post("/api/photos/ask", response_model=PhotoAnswer)
def ask_about_photo(payload: PhotoAskIn, user: dict = Depends(auth.current_user)) -> PhotoAnswer:
    """Ask a question about one stored photo, with the image attached."""
    photo = photo_store.get(payload.photo_id, user["namespace"])
    if photo is None or not photo.path.exists():
        raise HTTPException(status_code=404, detail="Photo not found.")

    started = time.monotonic()
    encoded = base64.b64encode(photo.path.read_bytes()).decode("ascii")
    answer = reeve_gateway.ask_with_photo(payload.question, encoded, photo.media_type, user["namespace"])
    quota.spend("photo_ask_attached")

    return PhotoAnswer(
        answer=answer,
        mode="attached",
        note="The image was sent with the question, so the vision model read the "
        "original rather than relying on the caption.",
        queries_used=1,
        took_ms=int((time.monotonic() - started) * 1000),
    )


@router.post("/api/photos/ask-unattached", response_model=PhotoAnswer)
def ask_without_attaching(payload: SearchIn, user: dict = Depends(auth.current_user)) -> PhotoAnswer:
    """Same question, no image attached — does the retrieval lane find it alone?"""
    started = time.monotonic()
    stored = len(photo_store.list_for(user["namespace"]))
    answer = reeve_gateway.ask(payload.query, user["namespace"])
    quota.spend("photo_ask_lane")

    if stored < IMAGE_LANE_MIN_SAMPLE:
        note = (
            f"Only {stored} photo(s) stored. The image lane stays silent below "
            f"{IMAGE_LANE_MIN_SAMPLE}, so this answer came from text alone."
        )
    else:
        note = (
            "No image attached. If this matches the attached answer, the image "
            "lane selected the photo on its own."
        )

    return PhotoAnswer(
        answer=answer,
        mode="lane",
        note=note,
        queries_used=1,
        took_ms=int((time.monotonic() - started) * 1000),
    )


@router.post("/api/photos/search")
def search_photos(payload: SearchIn, user: dict = Depends(auth.current_user)) -> dict:
    """Find a photo by what it looks like, not by what its caption says."""
    raw = reeve_gateway.search_photos(payload.query, user["namespace"])
    quota.spend("photo_search")
    return {"raw": raw, "found": "No matching photo memories" not in raw, "queries_used": 1}


@router.post("/api/photos/search-by-image")
async def search_by_image(file: UploadFile = File(...), user: dict = Depends(auth.current_user)) -> dict:
    """Image-to-image: find the stored photo that looks like this one."""
    media_type = (file.content_type or "").lower()
    if media_type not in settings.allowed_media_types:
        raise HTTPException(status_code=415, detail=f"Unsupported image type '{media_type}'.")

    raw_bytes = await file.read()
    if len(raw_bytes) > settings.max_image_bytes:
        raise HTTPException(status_code=413, detail="Image too large.")

    encoded = base64.b64encode(raw_bytes).decode("ascii")
    raw = await run_in_threadpool(reeve_gateway.search_photos_by_image, encoded, media_type, user["namespace"])
    quota.spend("photo_search_by_image")
    return {"raw": raw, "found": "No matching photo memories" not in raw, "queries_used": 1}


@router.post("/api/photos/upload-and-ask", response_model=PhotoAnswer)
async def upload_and_ask(
    file: UploadFile = File(...),
    question: str = Form(...),
    user: dict = Depends(auth.current_user),
) -> PhotoAnswer:
    """Ask about a photo that was never stored — useful for 'is this the same
    whiteboard as the one from Tuesday?'"""
    media_type = (file.content_type or "").lower()
    if media_type not in settings.allowed_media_types:
        raise HTTPException(status_code=415, detail=f"Unsupported image type '{media_type}'.")

    raw_bytes = await file.read()
    if len(raw_bytes) > settings.max_image_bytes:
        raise HTTPException(status_code=413, detail="Image too large.")

    started = time.monotonic()
    encoded = base64.b64encode(raw_bytes).decode("ascii")
    answer = await run_in_threadpool(
        reeve_gateway.ask_with_photo, question, encoded, media_type, user["namespace"]
    )
    quota.spend("photo_ask_attached")

    return PhotoAnswer(
        answer=answer,
        mode="attached",
        note="Asked against an image that was not stored as a memory.",
        queries_used=1,
        took_ms=int((time.monotonic() - started) * 1000),
    )


@router.post("/api/photos/ask-base64", response_model=PhotoAnswer)
async def ask_with_base64_photo(
    payload: PhotoBase64AskIn,
    user: dict = Depends(auth.current_user),
) -> PhotoAnswer:
    """Ask about a photo sent as JSON rather than multipart.

    The base64 twin of upload-and-ask, for React Native — see
    routes/capture.py for why its FormData cannot be used.
    """
    import binascii

    try:
        raw = base64.b64decode(payload.image_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Image data is not valid base64.") from exc

    media_type = payload.media_type.lower()
    if media_type not in settings.allowed_media_types:
        raise HTTPException(status_code=415, detail=f"Unsupported image type '{media_type}'.")
    if len(raw) > settings.max_image_bytes:
        raise HTTPException(status_code=413, detail="Image too large.")

    started = time.monotonic()
    answer = await run_in_threadpool(
        reeve_gateway.ask_with_photo,
        payload.question,
        payload.image_base64,
        media_type,
        user["namespace"],
    )
    quota.spend("photo_ask_attached")

    return PhotoAnswer(
        answer=answer,
        mode="attached",
        note="The image was sent with the question, so the vision model read it directly.",
        queries_used=1,
        took_ms=int((time.monotonic() - started) * 1000),
    )
