"""Chat session endpoints.

Every route is scoped to the caller's namespace, same as the memory routes — a
transcript is as personal as the facts in it.

Note what is absent: nothing here touches Reeve. Sessions organise
conversations; they do not partition memory. Asking a question in one chat
searches everything the account has ever stored, which is the point.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import auth, chats

router = APIRouter()


class ChatCreateIn(BaseModel):
    title: str = ""


class ChatRenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=60)


class MessageIn(BaseModel):
    role: str = Field(pattern="^(you|Carrel|note)$")
    text: str = ""
    # Server-hosted thumbnail rather than the device's local file:// path, so a
    # transcript still shows its photos when opened on another device.
    thumb_url: str | None = None
    meta: str | None = None
    question: str | None = None


class MessagesIn(BaseModel):
    messages: list[MessageIn] = Field(min_length=1)


@router.get("/api/chats")
def list_chats(user: dict = Depends(auth.current_user)) -> list[dict]:
    return chats.list_chats(user["namespace"])


@router.post("/api/chats")
def create_chat(payload: ChatCreateIn, user: dict = Depends(auth.current_user)) -> dict:
    return chats.create(user["namespace"], payload.title)


@router.get("/api/chats/{chat_id}")
def get_chat(chat_id: str, user: dict = Depends(auth.current_user)) -> dict:
    chat = chats.get(user["namespace"], chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="No such chat.")
    return chat


@router.post("/api/chats/{chat_id}/messages")
def append_messages(
    chat_id: str, payload: MessagesIn, user: dict = Depends(auth.current_user)
) -> dict:
    chat = chats.append(
        user["namespace"], chat_id, [m.model_dump() for m in payload.messages]
    )
    if chat is None:
        raise HTTPException(status_code=404, detail="No such chat.")
    return chat


@router.patch("/api/chats/{chat_id}")
def rename_chat(
    chat_id: str, payload: ChatRenameIn, user: dict = Depends(auth.current_user)
) -> dict:
    if not chats.rename(user["namespace"], chat_id, payload.title):
        raise HTTPException(status_code=404, detail="No such chat.")
    return {"ok": True}


@router.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str, user: dict = Depends(auth.current_user)) -> dict:
    """Deletes the transcript, not the memories.

    Anything said in this conversation stays answerable from any other chat —
    the facts live in Reeve, not here.
    """
    if not chats.delete(user["namespace"], chat_id):
        raise HTTPException(status_code=404, detail="No such chat.")
    return {"ok": True, "memories_kept": True}
