"""Postgres, and the reason the JSON files had to go.

The files were the right call for one laptop: readable, no migrations, no server
to run. They stop being the right call the moment two requests arrive at once.
`path.write_text` is not atomic — a crash or an overlapping write between the
truncate and the flush leaves `users.json` half-written, which is every account
on the deployment. A lock inside one process does not help when the process is
restarted mid-write, and helps even less when there is more than one worker.

So: one connection pool, one schema, and writes that either happen or do not.

The schema is applied at import rather than through a migration tool. There is
one deployment and the statements are all `IF NOT EXISTS`, so running them on
every boot costs a few milliseconds and removes an entire class of "did you
remember to migrate" failure. When there are two deployments, this needs Alembic
and this comment should be deleted.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings

_pool: ConnectionPool | None = None


def configured() -> bool:
    return bool(settings.database_url)


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        if not settings.database_url:
            raise RuntimeError(
                "DATABASE_URL is not set. The app stores accounts, conversations "
                "and photo metadata in Postgres; there is no file fallback."
            )
        _pool = ConnectionPool(
            settings.database_url,
            min_size=1,
            # The box this runs on has ~1GB of RAM to spare and Postgres is
            # capped at 40 connections. A pool that can outgrow the server is a
            # failure that only appears under load.
            max_size=8,
            timeout=10,
            kwargs={"row_factory": dict_row},
            open=True,
        )
    return _pool


@contextmanager
def cursor(commit: bool = False):
    """A cursor from the pool, rolled back on error rather than left dirty."""
    with pool().connection() as conn:
        with conn.cursor() as cur:
            yield cur
        if commit:
            conn.commit()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    email             TEXT PRIMARY KEY,
    name              TEXT NOT NULL DEFAULT '',
    -- Null for accounts that only ever sign in with Google. login() reads the
    -- absence as "cannot be signed into that way" rather than as an error.
    salt              TEXT,
    password_hash     TEXT,
    namespace         TEXT NOT NULL UNIQUE,
    google_sub        TEXT NOT NULL DEFAULT '',
    avatar_url        TEXT NOT NULL DEFAULT '',
    terms_version     TEXT NOT NULL DEFAULT '',
    terms_accepted_at DOUBLE PRECISION,
    created_at        DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    email      TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
    created_at DOUBLE PRECISION NOT NULL
);
-- Deleting an account must not leave a usable token behind; the cascade above
-- is what guarantees it rather than remembering to do it in application code.
CREATE INDEX IF NOT EXISTS sessions_email_idx ON sessions (email);

CREATE TABLE IF NOT EXISTS chats (
    id         TEXT PRIMARY KEY,
    namespace  TEXT NOT NULL,
    title      TEXT NOT NULL DEFAULT 'New chat',
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS chats_namespace_idx ON chats (namespace, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id         BIGSERIAL PRIMARY KEY,
    chat_id    TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,
    text       TEXT NOT NULL DEFAULT '',
    thumb_url  TEXT,
    meta       TEXT,
    question   TEXT,
    created_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_chat_idx ON messages (chat_id, id);

CREATE TABLE IF NOT EXISTS photos (
    photo_id   TEXT PRIMARY KEY,
    namespace  TEXT NOT NULL,
    caption    TEXT NOT NULL DEFAULT '',
    media_type TEXT NOT NULL,
    -- Where the bytes actually are. Not on this machine: the box runs a
    -- production MCP server on the same 6GB volume, and photographs are the
    -- only thing here that grows without bound.
    storage_key TEXT NOT NULL,
    stored_at  DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS photos_namespace_idx ON photos (namespace, stored_at DESC);

-- The settling tray. It lived in process memory, which was fine for one
-- long-running server and wrong for anything that restarts or scales: a deploy
-- would erase every "still settling" marker and the app would claim writes were
-- indexed that it had never confirmed.
CREATE TABLE IF NOT EXISTS pending_writes (
    id          TEXT PRIMARY KEY,
    namespace   TEXT NOT NULL,
    pending_id  TEXT,
    kind        TEXT NOT NULL,
    preview     TEXT NOT NULL DEFAULT '',
    batch_id    TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL,
    created_at  DOUBLE PRECISION NOT NULL,
    verified_at DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS pending_namespace_idx ON pending_writes (namespace, created_at DESC);

-- Failed sign-in attempts, for rate limiting.
--
-- In Postgres rather than process memory for the same reason the settling tray
-- moved: a restart would empty it, and "restart the process" is not a barrier
-- to somebody guessing passwords. Only failures are recorded — a successful
-- sign-in is not evidence of anything worth throttling.
CREATE TABLE IF NOT EXISTS login_failures (
    id          BIGSERIAL PRIMARY KEY,
    email       TEXT NOT NULL,
    client_ip   TEXT NOT NULL DEFAULT '',
    at          DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS login_failures_email_idx ON login_failures (email, at DESC);
CREATE INDEX IF NOT EXISTS login_failures_ip_idx ON login_failures (client_ip, at DESC);

-- Reset emails asked for, so that endpoint can be throttled on its own counter.
--
-- Deliberately NOT the login-failure counter. Sharing it meant somebody locked
-- out by wrong passwords could not ask for a reset — the exact person who needs
-- one. What this protects is different too: not password guessing, but flooding
-- an inbox and spending the mail quota.
CREATE TABLE IF NOT EXISTS mail_requests (
    id        BIGSERIAL PRIMARY KEY,
    email     TEXT NOT NULL,
    client_ip TEXT NOT NULL DEFAULT '',
    at        DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS mail_requests_email_idx ON mail_requests (email, at DESC);
CREATE INDEX IF NOT EXISTS mail_requests_ip_idx ON mail_requests (client_ip, at DESC);

-- Single-use links sent by email: verification and password reset.
--
-- The token is stored HASHED. A reset token is a working credential for an
-- account until it is used, so a database dump — or a backup, or a stray log —
-- must not hand out live links. Same reasoning as password hashes, applied to
-- the thing that can replace a password.
CREATE TABLE IF NOT EXISTS email_tokens (
    token_hash TEXT PRIMARY KEY,
    email      TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
    purpose    TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    used_at    DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS email_tokens_email_idx ON email_tokens (email, purpose);

-- Addresses the mail provider has told us are undeliverable.
--
-- Whether a *mailbox* exists cannot be known at request time by anyone: the
-- only synchronous test is an SMTP probe, which is blocked, treated as abuse,
-- and — because it distinguishes real addresses from fake ones — is itself the
-- enumeration tool this whole flow exists to avoid.
--
-- So the answer arrives afterwards, as a bounce, and is remembered. The first
-- attempt on a mistyped address is silent; every later one says so.
CREATE TABLE IF NOT EXISTS bounced_addresses (
    email      TEXT PRIMARY KEY,
    reason     TEXT NOT NULL DEFAULT '',
    bounced_at DOUBLE PRECISION NOT NULL
);

-- Columns added after a table first shipped.
--
-- CREATE TABLE IF NOT EXISTS does NOT reconcile columns: once the table exists
-- it is a no-op, and a column added to the statement above is silently never
-- created. That is not theoretical — `pending_id` was added here after the
-- table had been created, so every note write crashed on INSERT with
-- UndefinedColumn while the schema file looked perfectly correct.
--
-- So every column added from now on needs a line here too. When that becomes
-- tedious, that is the signal to adopt Alembic rather than to start guessing.
ALTER TABLE pending_writes ADD COLUMN IF NOT EXISTS pending_id TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS google_sub TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE;
"""


def init_schema() -> None:
    """Idempotent. Safe to run on every boot, and it does."""
    with cursor(commit=True) as cur:
        cur.execute(SCHEMA)


def close() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
