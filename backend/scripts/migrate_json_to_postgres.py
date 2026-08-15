"""One-way move: the JSON files and local photos into Postgres and S3.

Run once, from the machine that holds `backend/var/`. It is idempotent — every
insert is ON CONFLICT DO NOTHING — so a partial run can simply be repeated.

Nothing is deleted. The JSON files stay exactly where they are, because the
first rule of a migration is that it must be possible to discover it went wrong
afterwards. Delete `var/` by hand once the deployment has proved itself.

    cd backend && .venv/bin/python scripts/migrate_json_to_postgres.py
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.db import cursor, init_schema  # noqa: E402

VAR = settings.var_dir


def _load(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def migrate_users() -> tuple[int, int]:
    users = _load(VAR / "users.json")
    sessions = _load(VAR / "sessions.json")
    moved_users = moved_sessions = 0
    with cursor(commit=True) as cur:
        for email, rec in users.items():
            cur.execute(
                """
                INSERT INTO users (email, name, salt, password_hash, namespace,
                                   google_sub, avatar_url, terms_version,
                                   terms_accepted_at, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (email) DO NOTHING
                """,
                (
                    email,
                    rec.get("name", ""),
                    rec.get("salt"),
                    rec.get("hash"),
                    rec["namespace"],
                    rec.get("google_sub", ""),
                    rec.get("avatar_url", ""),
                    rec.get("terms_version", ""),
                    rec.get("terms_accepted_at"),
                    rec.get("created_at", time.time()),
                ),
            )
            moved_users += cur.rowcount
        for token, rec in sessions.items():
            # Only sessions whose account made it across; a token pointing at a
            # missing user would violate the foreign key, which is the point.
            if rec.get("email") not in users:
                continue
            cur.execute(
                "INSERT INTO sessions (token, email, created_at) VALUES (%s, %s, %s)"
                " ON CONFLICT (token) DO NOTHING",
                (token, rec["email"], rec.get("created_at", time.time())),
            )
            moved_sessions += cur.rowcount
    return moved_users, moved_sessions


def migrate_chats() -> tuple[int, int]:
    chats = messages = 0
    chat_dir = VAR / "chats"
    if not chat_dir.exists():
        return 0, 0
    with cursor(commit=True) as cur:
        for path in sorted(chat_dir.glob("*.json")):
            namespace = path.stem
            data = _load(path).get("chats", {})
            for chat_id, chat in data.items():
                cur.execute(
                    """
                    INSERT INTO chats (id, namespace, title, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        chat_id,
                        namespace,
                        chat.get("title", "New chat"),
                        chat.get("created_at", time.time()),
                        chat.get("updated_at", time.time()),
                    ),
                )
                if cur.rowcount == 0:
                    continue  # already migrated; do not double its messages
                chats += 1
                for m in chat.get("messages", []):
                    cur.execute(
                        """
                        INSERT INTO messages (chat_id, role, text, thumb_url,
                                              meta, question, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            chat_id,
                            m.get("role", "you"),
                            m.get("text", "") or "",
                            m.get("thumb_url"),
                            m.get("meta"),
                            m.get("question"),
                            m.get("created_at", time.time()),
                        ),
                    )
                    messages += 1
    return chats, messages


def migrate_photos() -> tuple[int, int]:
    """Metadata to Postgres, bytes to S3, keeping the original photo_id.

    The id has to survive: it is written into every transcript as
    `/api/photos/<id>/raw`, so a new one would break each of those links.
    """
    from app import photo_store

    index = _load(VAR / "photos.json")
    moved = skipped = 0
    for photo_id, rec in index.items():
        namespace = rec.get("namespace", "")
        if not namespace:
            # Predates accounts and cannot be attributed to anyone. The store
            # already treats these as belonging to nobody; moving them would be
            # inventing an owner.
            skipped += 1
            continue
        source = settings.photo_dir / rec["filename"]
        if not source.exists():
            skipped += 1
            continue

        media_type = rec.get("media_type", "image/jpeg")
        key = photo_store._key_for(namespace, photo_id, media_type)
        photo_store._client().put_object(
            Bucket=settings.s3_bucket, Key=key, Body=source.read_bytes(), ContentType=media_type
        )
        with cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO photos (photo_id, namespace, caption, media_type,
                                    storage_key, stored_at)
                VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (photo_id) DO NOTHING
                """,
                (
                    photo_id,
                    namespace,
                    rec.get("caption", ""),
                    media_type,
                    key,
                    rec.get("stored_at", time.time()),
                ),
            )
        moved += 1
    return moved, skipped


if __name__ == "__main__":
    init_schema()
    users, sessions = migrate_users()
    chats, messages = migrate_chats()
    photos, skipped = migrate_photos()
    print(f"users     {users}")
    print(f"sessions  {sessions}")
    print(f"chats     {chats}  ({messages} messages)")
    print(f"photos    {photos}  ({skipped} skipped: unowned or file missing)")
    print("\nThe JSON files are untouched. Remove var/ by hand once this has proved itself.")
