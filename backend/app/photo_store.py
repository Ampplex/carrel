"""Copies of uploaded photos: metadata in Postgres, bytes in S3.

Reeve retains the original server-side — that is what makes it possible to
re-read a photo months later for a question nobody anticipated — but it exposes
no client-facing "fetch image by id" call. So the app keeps its own copy, for
two things it cannot otherwise do: render thumbnails, and re-attach the bytes
when someone asks about a specific photo.

The bytes are deliberately NOT on the application server. That box runs a
production MCP server on a 6GB volume with about a gigabyte free, and
photographs are the only thing in this system that grows without bound. Filling
that disk would take Reeve down with it. S3 has no such ceiling, and the AWS
credentials already exist there for Reeve's own image retention.

This is still a display cache, not the system of record. Losing the bucket loses
the thumbnails, not the memories.
"""

from __future__ import annotations

import time
import uuid
from functools import lru_cache

from pydantic import BaseModel

from app.config import settings
from app.db import cursor

_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


class PhotoStoreUnavailable(RuntimeError):
    """No bucket configured. Raised rather than silently dropping the bytes."""


class StoredPhoto(BaseModel):
    photo_id: str
    caption: str
    media_type: str
    stored_at: float
    namespace: str
    storage_key: str


@lru_cache(maxsize=1)
def _client():
    """One boto3 client for the process. Created lazily so the app still starts
    — and every non-photo route still works — when S3 is not configured."""
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise PhotoStoreUnavailable(
            'boto3 is not installed. Reinstall the backend: pip install -e "backend[dev]"'
        ) from exc
    if not settings.s3_bucket:
        raise PhotoStoreUnavailable(
            "CARREL_S3_BUCKET is not set, so there is nowhere to put photographs."
        )
    return boto3.client("s3", region_name=settings.s3_region)


def configured() -> bool:
    return bool(settings.s3_bucket)


def _key_for(namespace: str, photo_id: str, media_type: str) -> str:
    """Namespaced so a bucket listing cannot mix two people's photographs, and
    so a whole account's images can be removed with one prefix delete."""
    ext = _EXTENSIONS.get(media_type, ".bin")
    return f"{settings.s3_prefix}/{namespace}/{photo_id}{ext}"


def save(raw: bytes, caption: str, media_type: str, namespace: str) -> StoredPhoto:
    photo_id = uuid.uuid4().hex
    key = _key_for(namespace, photo_id, media_type)

    # Bytes first: a row pointing at an object that does not exist is a broken
    # thumbnail forever, while an object with no row is merely orphaned.
    _client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=raw,
        ContentType=media_type,
    )

    stored_at = time.time()
    with cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO photos (photo_id, namespace, caption, media_type, storage_key, stored_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (photo_id, namespace, caption, media_type, key, stored_at),
        )
    return StoredPhoto(
        photo_id=photo_id,
        caption=caption,
        media_type=media_type,
        stored_at=stored_at,
        namespace=namespace,
        storage_key=key,
    )


def get(photo_id: str, namespace: str) -> StoredPhoto | None:
    """Look up a photo, but only within the caller's own account.

    The namespace is in the WHERE clause, not checked afterwards. A record that
    can be returned to the wrong account and relies on the caller to notice is
    how a cache quietly becomes a leak.
    """
    with cursor() as cur:
        cur.execute(
            "SELECT * FROM photos WHERE photo_id = %s AND namespace = %s",
            (photo_id, namespace),
        )
        row = cur.fetchone()
    return StoredPhoto(**{k: row[k] for k in StoredPhoto.model_fields}) if row else None


def read_bytes(photo: StoredPhoto) -> bytes:
    obj = _client().get_object(Bucket=settings.s3_bucket, Key=photo.storage_key)
    return obj["Body"].read()


def list_for(namespace: str) -> list[StoredPhoto]:
    with cursor() as cur:
        cur.execute(
            "SELECT * FROM photos WHERE namespace = %s ORDER BY stored_at DESC",
            (namespace,),
        )
        rows = cur.fetchall()
    return [StoredPhoto(**{k: r[k] for k in StoredPhoto.model_fields}) for r in rows]


def delete_for(namespace: str) -> int:
    """Remove every photo belonging to one account, objects included.

    Used by account erasure. Deleting the row without the object would leave the
    bytes in the bucket after somebody asked for them to be gone — which is the
    difference between erasure and bookkeeping.
    """
    photos = list_for(namespace)
    if not photos:
        return 0

    try:
        client = _client()
        # 1000 keys per call is the API limit; batches keep erasure to one round
        # trip for any realistic account.
        for start in range(0, len(photos), 1000):
            batch = photos[start : start + 1000]
            client.delete_objects(
                Bucket=settings.s3_bucket,
                Delete={"Objects": [{"Key": p.storage_key} for p in batch]},
            )
    except PhotoStoreUnavailable:
        # No bucket configured: the rows are still this account's to remove, and
        # leaving them would misreport what was erased.
        pass

    with cursor(commit=True) as cur:
        cur.execute("DELETE FROM photos WHERE namespace = %s", (namespace,))
        return cur.rowcount
