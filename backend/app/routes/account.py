"""Account settings, and getting your data out of here.

Erasure has to reach every place data actually lives, and in this app that is
four separate stores:

  * Reeve   — the memories themselves, plus the photos it retained
  * photos  — Carrel's own local copies, kept for thumbnails
  * chats   — conversation transcripts
  * account — the login record and its sessions

Deleting three of four is worse than useless, because it looks complete. So the
response says exactly what went, and the two operations are kept distinct:
erasing memories leaves you signed in with an empty app, deleting the account
takes the login with it.

There is deliberately no soft-delete or grace period. Someone asking to be
forgotten should not have to trust a scheduler.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import auth, chats, photo_store, reeve_gateway

router = APIRouter()
log = logging.getLogger("carrel")

# Typed rather than tapped. A confirmation button can be hit by accident; typing
# the phrase cannot.
ERASE_PHRASE = "DELETE MY MEMORY"


class EraseIn(BaseModel):
    confirm: str


class AccountOut(BaseModel):
    email: str
    name: str
    memories_kept: bool = True


@router.get("/api/account", response_model=AccountOut)
def me(user: dict = Depends(auth.current_user)) -> AccountOut:
    return AccountOut(email=user["email"], name=user["name"])


def _erase_everything(namespace: str) -> dict:
    """Wipe every store for one account. Reeve first, because it is the one that
    can fail — if it does, nothing local is destroyed and the user can retry
    against a consistent state."""
    reeve = reeve_gateway.erase(namespace)

    photos = photo_store.delete_for(namespace)

    transcripts = 0
    for chat in chats.list_chats(namespace):
        if chats.delete(namespace, chat["id"]):
            transcripts += 1

    return {
        "memories": reeve.get("episodes", 0),
        "entities": reeve.get("entities", 0),
        "reeve_images": reeve.get("images_deleted", reeve.get("images", 0)),
        "local_photos": photos,
        "conversations": transcripts,
    }


@router.post("/api/account/erase")
def erase(payload: EraseIn, user: dict = Depends(auth.current_user)) -> dict:
    """Delete everything this account has stored, but keep the login."""
    if payload.confirm.strip() != ERASE_PHRASE:
        raise HTTPException(
            status_code=400, detail=f'Type "{ERASE_PHRASE}" exactly to confirm.'
        )

    result = _erase_everything(user["namespace"])
    log.info("erased account data for %s: %s", user["namespace"], result)
    return {"ok": True, "deleted": result, "account_kept": True}


@router.delete("/api/account")
def delete_account(payload: EraseIn, user: dict = Depends(auth.current_user)) -> dict:
    """Delete everything, then the account itself.

    The login goes last: if erasure fails partway, the account still exists and
    the operation can be retried. Removing the account first would leave
    orphaned memories nobody can reach or erase.
    """
    if payload.confirm.strip() != ERASE_PHRASE:
        raise HTTPException(
            status_code=400, detail=f'Type "{ERASE_PHRASE}" exactly to confirm.'
        )

    result = _erase_everything(user["namespace"])
    auth.delete_account(user["email"])
    log.info("deleted account %s", user["namespace"])
    return {"ok": True, "deleted": result, "account_kept": False}
