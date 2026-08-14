"""Health, capabilities, the pending tray, and the destructive reset.

The capability endpoint matters more than it looks. Vision, image retention and
async writes are all operator-controlled on the Reeve side, and if one is turned
off the app does not get an error — answers just quietly stop being grounded in
the image. Reading the live config on page load turns a silent degradation into
a visible red badge.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException

from app import auth, quota, reeve_gateway
from app.config import settings
from app.models import ResetIn
from app.pending import PendingWrite, registry

router = APIRouter()

_CONFIG_TTL_SECONDS = 300
_config_cache: dict = {"at": 0.0, "value": None}


@router.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "namespace": settings.namespace,
        "replay_mode": settings.demo_replay,
        "quota": quota.snapshot(),
    }


@router.get("/api/config")
def config() -> dict:
    """Live capability report, cached briefly. Free — does not cost a query."""
    now = time.time()
    if _config_cache["value"] is None or now - _config_cache["at"] > _CONFIG_TTL_SECONDS:
        _config_cache["value"] = reeve_gateway.config()
        _config_cache["at"] = now

    live = _config_cache["value"]
    return {
        **live,
        "capabilities": {
            "photo_questions": bool(live.get("vision_enabled")),
            "photo_reinterrogation": bool(live.get("image_retention_enabled")),
            "photo_search": bool(live.get("multimodal_image_search_enabled")),
            "async_writes": bool(live.get("async_write_enabled")),
        },
    }


@router.get("/api/pending", response_model=list[PendingWrite])
def pending() -> list[PendingWrite]:
    """Free, and called on a local timer only — never a network poll.

    Background polling for indexing status is the one pattern that would burn
    thousands of queries a day, so status here is computed from elapsed time and
    the only way to reach `indexed` is an explicit, user-triggered check.
    """
    return registry.list()


@router.post("/api/pending/{item_id}/verify")
def verify(item_id: str, user: dict = Depends(auth.current_user)) -> dict:
    """Check whether one write is really searchable yet. Costs one query.

    The UI prints that cost on the button. This is the only call that can move a
    write to `indexed`, because it is the only one that actually looks.
    """
    item = registry.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="No such pending write.")

    raw = reeve_gateway.context(item.preview, user["namespace"])
    quota.spend("verify")

    # Found and outside the not-yet-indexed block means genuinely searchable.
    long_term = raw.partition("Long-term memory context")[2]
    probe = item.preview[:40]
    found = bool(probe) and probe in long_term

    updated = registry.mark_verified(item_id, found)
    return {
        "status": updated.status if updated else "unknown",
        "found": found,
        "queries_used": 1,
    }


@router.post("/api/admin/reset")
def reset(payload: ResetIn, user: dict = Depends(auth.current_user)) -> dict:
    """Wipe the namespace. Irreversible, and broader than it sounds — it also
    cancels queued writes and deletes retained photos."""
    try:
        return reeve_gateway.reset(user["namespace"], payload.confirm)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
