"""Chat sessions — a way to organise conversations, and nothing more.

The important thing about a session is what it is NOT. It is not a memory
boundary. Every session in an account reads and writes the same Reeve namespace,
so a fact mentioned in one conversation is answerable from any other. That is
deliberate: the product is a memory, and a memory that forgot things when you
started a new chat would be a worse notes app.

What a session actually holds is the transcript — the bubbles on screen — so a
conversation survives a reload and follows you to another device.

Rows in Postgres, keyed by namespace rather than email, so nothing here carries
a personal identifier. It was one JSON file per account, which meant rewriting
the whole file to append one message: fine for a laptop, and a corruption risk
the moment two requests append at once.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from app.db import cursor

# Transcripts are for continuity, not archival. A cap keeps a long-running
# conversation from growing without limit; the memory itself is in Reeve and is
# unaffected by trimming what is displayed.
MAX_MESSAGES_PER_CHAT = 500


def _title_from(text: str) -> str:
    """First line, trimmed. Good enough that nobody has to name a chat."""
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    line = line.strip()
    if len(line) > 48:
        line = line[:47].rstrip() + "…"
    return line or "New chat"


def _summary(row: dict, count: int, preview: str) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "message_count": count,
        "preview": preview,
    }


def list_chats(namespace: str) -> list[dict[str, Any]]:
    """Most recently touched first — the order a drawer should show."""
    with cursor() as cur:
        cur.execute(
            """
            SELECT c.*,
                   (SELECT count(*) FROM messages m WHERE m.chat_id = c.id) AS message_count,
                   (SELECT m.text FROM messages m
                     WHERE m.chat_id = c.id AND m.text <> ''
                     ORDER BY m.id DESC LIMIT 1) AS preview
            FROM chats c
            WHERE c.namespace = %s
            ORDER BY c.updated_at DESC
            """,
            (namespace,),
        )
        rows = cur.fetchall()
    return [
        _summary(r, r["message_count"], (r["preview"] or "")[:80]) for r in rows
    ]


def create(namespace: str, title: str = "") -> dict[str, Any]:
    chat_id = uuid.uuid4().hex
    now = time.time()
    with cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO chats (id, namespace, title, created_at, updated_at)"
            " VALUES (%s, %s, %s, %s, %s)",
            (chat_id, namespace, (title or "New chat")[:60], now, now),
        )
    return {
        "id": chat_id,
        "title": (title or "New chat")[:60],
        "created_at": now,
        "updated_at": now,
        "message_count": 0,
        "preview": "",
    }


def get(namespace: str, chat_id: str) -> dict[str, Any] | None:
    """A chat and its transcript, or None if it is not this account's.

    The namespace is part of the WHERE clause rather than checked afterwards:
    a lookup that can return another account's row and rely on the caller to
    notice is a leak waiting for one forgetful caller.
    """
    with cursor() as cur:
        cur.execute(
            "SELECT * FROM chats WHERE id = %s AND namespace = %s", (chat_id, namespace)
        )
        chat = cur.fetchone()
        if chat is None:
            return None
        cur.execute(
            "SELECT role, text, thumb_url, meta, question, created_at"
            " FROM messages WHERE chat_id = %s ORDER BY id",
            (chat_id,),
        )
        messages = cur.fetchall()
    return {
        "id": chat["id"],
        "title": chat["title"],
        "created_at": chat["created_at"],
        "updated_at": chat["updated_at"],
        "messages": [dict(m) for m in messages],
    }


def append(namespace: str, chat_id: str, messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Add messages, naming the chat from the first thing said in it."""
    now = time.time()
    with cursor(commit=True) as cur:
        cur.execute(
            "SELECT * FROM chats WHERE id = %s AND namespace = %s", (chat_id, namespace)
        )
        chat = cur.fetchone()
        if chat is None:
            return None

        for m in messages:
            cur.execute(
                """
                INSERT INTO messages (chat_id, role, text, thumb_url, meta, question, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    chat_id,
                    m.get("role", "you"),
                    m.get("text", "") or "",
                    m.get("thumb_url"),
                    m.get("meta"),
                    m.get("question"),
                    m.get("created_at") or now,
                ),
            )

        # Auto-title from the first thing the person actually said, so nobody
        # has to name a conversation to find it again.
        if chat["title"] in ("", "New chat"):
            first = next(
                (m for m in messages if m.get("role") == "you" and (m.get("text") or "").strip()),
                None,
            )
            if first:
                cur.execute(
                    "UPDATE chats SET title = %s WHERE id = %s",
                    (_title_from(first["text"]), chat_id),
                )

        # Trim the oldest beyond the cap. Deleting by id keeps the newest,
        # which is the half anyone scrolling back actually wants.
        cur.execute(
            """
            DELETE FROM messages WHERE chat_id = %s AND id NOT IN (
                SELECT id FROM messages WHERE chat_id = %s ORDER BY id DESC LIMIT %s
            )
            """,
            (chat_id, chat_id, MAX_MESSAGES_PER_CHAT),
        )
        cur.execute("UPDATE chats SET updated_at = %s WHERE id = %s", (now, chat_id))

    return get(namespace, chat_id)


def rename(namespace: str, chat_id: str, title: str) -> bool:
    with cursor(commit=True) as cur:
        cur.execute(
            "UPDATE chats SET title = %s, updated_at = %s WHERE id = %s AND namespace = %s",
            ((title or "New chat")[:60], time.time(), chat_id, namespace),
        )
        return cur.rowcount > 0


def delete(namespace: str, chat_id: str) -> bool:
    """Removes the transcript. The memories stay — see the module docstring, and
    the line the drawer shows under the delete confirmation."""
    with cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM chats WHERE id = %s AND namespace = %s", (chat_id, namespace)
        )
        return cur.rowcount > 0
