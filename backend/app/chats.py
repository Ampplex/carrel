"""Chat sessions — a way to organise conversations, and nothing more.

The important thing about a session is what it is NOT. It is not a memory
boundary. Every session in an account reads and writes the same Reeve
namespace, so a fact mentioned in one conversation is answerable from any other.
That is deliberate: the product is a memory, and a memory that forgot things
when you started a new chat would be a worse notes app.

What a session actually holds is the transcript — the bubbles on screen — so a
conversation survives a reload and follows you to another device. Losing the
whole thread on every app restart was the real gap; the memory itself was never
at risk.

Storage is one JSON file per account under `var/chats/`. Filed by namespace
rather than email, so nothing here carries a personal identifier.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any

from app.config import settings

_DIR = settings.var_dir / "chats"
_lock = threading.Lock()

# Transcripts are for continuity, not archival. A cap keeps a long-running
# conversation from growing a file without limit; the memory itself is in Reeve
# and is not affected by trimming what is displayed.
MAX_MESSAGES_PER_CHAT = 500


def _path(namespace: str):
    return _DIR / f"{namespace}.json"


def _read(namespace: str) -> dict[str, Any]:
    path = _path(namespace)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"chats": {}}


def _write(namespace: str, data: dict[str, Any]) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    path = _path(namespace)
    path.write_text(json.dumps(data, indent=2))
    try:
        os.chmod(path, 0o600)  # transcripts are personal even if memory is elsewhere
    except OSError:
        pass


def _title_from(text: str) -> str:
    """First line, trimmed. Good enough that nobody has to name a chat."""
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    line = line.strip()
    if len(line) > 48:
        line = line[:47].rstrip() + "…"
    return line or "New chat"


def list_chats(namespace: str) -> list[dict[str, Any]]:
    """Newest first, with a preview — the list view never loads transcripts."""
    with _lock:
        data = _read(namespace)
    out = []
    for chat_id, chat in data["chats"].items():
        messages = chat.get("messages", [])
        last = messages[-1] if messages else None
        out.append(
            {
                "id": chat_id,
                "title": chat.get("title") or "New chat",
                "created_at": chat.get("created_at", 0),
                "updated_at": chat.get("updated_at", 0),
                "message_count": len(messages),
                "preview": (last or {}).get("text", "")[:80],
            }
        )
    return sorted(out, key=lambda c: c["updated_at"], reverse=True)


def create(namespace: str, title: str = "") -> dict[str, Any]:
    chat_id = uuid.uuid4().hex
    now = time.time()
    with _lock:
        data = _read(namespace)
        data["chats"][chat_id] = {
            "title": title.strip() or "New chat",
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }
        _write(namespace, data)
    return {"id": chat_id, "title": title.strip() or "New chat", "created_at": now,
            "updated_at": now, "message_count": 0, "preview": ""}


def get(namespace: str, chat_id: str) -> dict[str, Any] | None:
    with _lock:
        chat = _read(namespace)["chats"].get(chat_id)
    if chat is None:
        return None
    return {"id": chat_id, **chat}


def append(namespace: str, chat_id: str, messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Append rendered messages to a transcript.

    The client sends what it drew rather than the server reconstructing it: the
    bubbles include things the server never sees, like which local photo was
    attached and how long an answer took.
    """
    with _lock:
        data = _read(namespace)
        chat = data["chats"].get(chat_id)
        if chat is None:
            return None

        now = time.time()
        for message in messages:
            chat["messages"].append({**message, "created_at": message.get("created_at", now)})

        # Name the chat after its first real utterance, so the list is readable
        # without anyone being asked to title anything.
        if chat.get("title") in (None, "", "New chat"):
            first_said = next(
                (m.get("text") for m in chat["messages"] if m.get("role") == "you" and m.get("text")),
                "",
            )
            if first_said:
                chat["title"] = _title_from(first_said)

        if len(chat["messages"]) > MAX_MESSAGES_PER_CHAT:
            chat["messages"] = chat["messages"][-MAX_MESSAGES_PER_CHAT:]

        chat["updated_at"] = now
        _write(namespace, data)
    return {"id": chat_id, **chat}


def rename(namespace: str, chat_id: str, title: str) -> bool:
    with _lock:
        data = _read(namespace)
        chat = data["chats"].get(chat_id)
        if chat is None:
            return False
        chat["title"] = title.strip()[:60] or "New chat"
        chat["updated_at"] = time.time()
        _write(namespace, data)
    return True


def delete(namespace: str, chat_id: str) -> bool:
    """Removes the transcript only.

    Nothing said in the chat is forgotten — those facts live in Reeve and stay
    answerable. Deleting a conversation tidies the list; it is not erasure, and
    the UI should not imply otherwise.
    """
    with _lock:
        data = _read(namespace)
        if data["chats"].pop(chat_id, None) is None:
            return False
        _write(namespace, data)
    return True
