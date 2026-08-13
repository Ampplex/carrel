"""Tracks writes that Reeve has accepted but not yet indexed.

Reeve acknowledges a write immediately and builds the knowledge graph behind it,
so there is a window — reported as roughly 10 to 60 seconds — where a memory
exists but may not be findable. Most demos hide that window and hope nobody
stores something and immediately asks about it on stage.

This app shows it instead. The registry below is what the UI's pending tray
reads, and its statuses are deliberately careful:

  * `indexing`             — accepted, still settling.
  * `likely_indexed`       — enough time has passed, but nobody has checked.
  * `indexed`              — a verification probe actually found it.

Nothing is ever promoted to `indexed` by a timer. That distinction is the whole
point: `likely_indexed` is an honest guess, `indexed` is a measurement.

State is per-process and deliberately not persisted — it describes what this
server instance has seen this session, not a durable record.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Literal

from pydantic import BaseModel

Status = Literal["indexing", "likely_indexed", "indexed", "failed"]

# Reeve's documented settle window. Past this we stop calling it "indexing", but
# we still refuse to claim it is indexed without evidence.
SETTLE_SECONDS = 60


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


class PendingRegistry:
    def __init__(self) -> None:
        self._items: dict[str, PendingWrite] = {}
        self._lock = threading.Lock()

    def add(
        self,
        *,
        kind: Literal["note", "photo"],
        preview: str,
        batch_id: str,
        store_result: dict | None,
    ) -> PendingWrite:
        # A synchronous write comes back already stored; there is nothing to wait
        # for, so record it as measured rather than assumed.
        already_indexed = bool(store_result and store_result.get("stored"))
        item = PendingWrite(
            id=uuid.uuid4().hex,
            pending_id=(store_result or {}).get("pending_id"),
            kind=kind,
            preview=preview[:120],
            batch_id=batch_id,
            created_at=time.time(),
            status="indexed" if already_indexed else "indexing",
            verified_at=time.time() if already_indexed else None,
        )
        with self._lock:
            self._items[item.id] = item
        return item

    def get(self, item_id: str) -> PendingWrite | None:
        with self._lock:
            return self._items.get(item_id)

    def mark_verified(self, item_id: str, found: bool) -> PendingWrite | None:
        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                return None
            if found:
                item.status = "indexed"
                item.verified_at = time.time()
            return item

    def list(self) -> list[PendingWrite]:
        """Current view, with time-based statuses refreshed.

        `likely_indexed` is applied here rather than by a background task: there
        is no timer thread and no polling, so this stays free.
        """
        now = time.time()
        with self._lock:
            items = list(self._items.values())
            for item in items:
                if item.status == "indexing" and now - item.created_at > SETTLE_SECONDS:
                    item.status = "likely_indexed"
            # Drop confirmed writes shortly after they go green so the tray does
            # not grow without bound during a long session.
            self._items = {
                key: value
                for key, value in self._items.items()
                if not (value.status == "indexed" and value.verified_at and now - value.verified_at > 30)
            }
        return sorted(items, key=lambda i: i.created_at, reverse=True)

    def unsettled_count(self) -> int:
        """How many writes could still be missing from an answer."""
        return sum(1 for item in self.list() if item.status in ("indexing", "likely_indexed"))


registry = PendingRegistry()
