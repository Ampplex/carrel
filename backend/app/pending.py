"""Tracks writes that Reeve has accepted but not yet indexed.

Reeve acknowledges a write immediately and builds the knowledge graph behind it,
so there is a window — roughly 10 to 60 seconds — where a memory exists but may
not be findable. Most demos hide that window and hope nobody stores something
and immediately asks about it on stage. This app shows it instead:

  * `indexing`       — accepted, still settling.
  * `likely_indexed` — enough time has passed, but nobody has checked.
  * `indexed`        — a verification probe actually found it.

Nothing is ever promoted to `indexed` by a timer. `likely_indexed` is an honest
guess; `indexed` is a measurement.

Two things changed when this moved off a process-local dict.

It is now **scoped to a namespace**. It never was, and every account's tray was
the same global dictionary — so `GET /api/pending` handed back other people's
in-flight writes, `preview` included, which is the first 120 characters of
whatever they had just typed. That was a cross-account leak sitting behind an
endpoint the chat screen polls every five seconds.

And it is now **durable**. The old comment said per-process state was fine
because it "describes what this server instance has seen this session". That
argument fails the first time the server restarts mid-settle: the tray empties,
the caveat disappears, and the app silently starts claiming completeness it
never verified. A restart is not evidence that a write landed.
"""

from __future__ import annotations

import time
import uuid
from typing import Literal

from pydantic import BaseModel

from app.db import cursor

Status = Literal["indexing", "likely_indexed", "indexed", "failed"]

# Reeve's documented settle window. Past this we stop calling it "indexing", but
# we still refuse to claim it is indexed without evidence.
SETTLE_SECONDS = 60

# After this, an unverified write leaves the tray entirely.
#
# It matches the server's own short-term buffer lifetime: past that point the
# write has left the buffer and is either in the graph or failed, so "still
# settling" has stopped being true. Keeping the pill was actively harmful —
# every answer inherited a caveat reading "1 memory is still settling" from a
# write that was nine minutes old and long since indexed. A warning that is
# always on teaches people to ignore warnings.
FORGET_UNVERIFIED_SECONDS = 300


class PendingWrite(BaseModel):
    id: str
    pending_id: str | None
    kind: Literal["note", "photo"]
    preview: str
    batch_id: str
    created_at: float
    status: Status = "indexing"
    verified_at: float | None = None

    @property
    def elapsed_s(self) -> float:
        return time.time() - self.created_at


def _row(r: dict) -> PendingWrite:
    return PendingWrite(
        id=r["id"],
        pending_id=r["pending_id"],
        kind=r["kind"],
        preview=r["preview"],
        batch_id=r["batch_id"],
        created_at=r["created_at"],
        status=r["status"],
        verified_at=r["verified_at"],
    )


class PendingRegistry:
    """Namespace-scoped. Every method takes one, and there is deliberately no
    default — a tray that can be read without saying whose it is was the bug."""

    def add(
        self,
        *,
        namespace: str,
        kind: Literal["note", "photo"],
        preview: str,
        batch_id: str,
        store_result: dict | None,
    ) -> PendingWrite:
        # A synchronous write comes back already stored; there is nothing to wait
        # for, so record it as measured rather than assumed.
        already_indexed = bool(store_result and store_result.get("stored"))
        now = time.time()
        item = PendingWrite(
            id=uuid.uuid4().hex,
            pending_id=(store_result or {}).get("pending_id"),
            kind=kind,
            preview=preview[:120],
            batch_id=batch_id,
            created_at=now,
            status="indexed" if already_indexed else "indexing",
            verified_at=now if already_indexed else None,
        )
        with cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO pending_writes
                    (id, namespace, pending_id, kind, preview, batch_id,
                     status, created_at, verified_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    item.id, namespace, item.pending_id, item.kind, item.preview,
                    item.batch_id, item.status, item.created_at, item.verified_at,
                ),
            )
        return item

    def get(self, namespace: str, item_id: str) -> PendingWrite | None:
        with cursor() as cur:
            cur.execute(
                "SELECT * FROM pending_writes WHERE id = %s AND namespace = %s",
                (item_id, namespace),
            )
            row = cur.fetchone()
        return _row(row) if row else None

    def mark_verified(self, namespace: str, item_id: str, found: bool) -> PendingWrite | None:
        if not found:
            return self.get(namespace, item_id)
        with cursor(commit=True) as cur:
            cur.execute(
                """
                UPDATE pending_writes SET status = 'indexed', verified_at = %s
                WHERE id = %s AND namespace = %s RETURNING *
                """,
                (time.time(), item_id, namespace),
            )
            row = cur.fetchone()
        return _row(row) if row else None

    def list(self, namespace: str) -> list[PendingWrite]:
        """Current view, with time-based statuses refreshed and stale rows swept.

        Both happen in the read, as they always did: there is no timer thread
        and no background task, so this stays free.
        """
        now = time.time()
        with cursor(commit=True) as cur:
            # Two ways out of the tray: confirmed and briefly shown, or old
            # enough that "still settling" is no longer honest.
            cur.execute(
                """
                DELETE FROM pending_writes
                WHERE namespace = %s AND (
                    (status = 'indexed' AND verified_at IS NOT NULL AND %s - verified_at > 30)
                    OR (status <> 'indexed' AND %s - created_at > %s)
                )
                """,
                (namespace, now, now, FORGET_UNVERIFIED_SECONDS),
            )
            cur.execute(
                """
                UPDATE pending_writes SET status = 'likely_indexed'
                WHERE namespace = %s AND status = 'indexing' AND %s - created_at > %s
                """,
                (namespace, now, SETTLE_SECONDS),
            )
            cur.execute(
                "SELECT * FROM pending_writes WHERE namespace = %s ORDER BY created_at DESC",
                (namespace,),
            )
            rows = cur.fetchall()
        return [_row(r) for r in rows]

    def unsettled_count(self, namespace: str) -> int:
        """How many of this account's writes could still be missing from an answer."""
        return sum(
            1 for item in self.list(namespace) if item.status in ("indexing", "likely_indexed")
        )


registry = PendingRegistry()
