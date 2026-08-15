"""Settling-tray tests. Zero quota.

The tray is the app's honesty device, so its two failure modes are both bad in
opposite directions: forget a write too early and an answer looks more complete
than it is; keep one forever and every answer carries a warning nobody believes.

These used to reach into `registry._items` to backdate a timestamp. The tray is
rows now, so ageing a write is an UPDATE — which is closer to what actually
happens anyway, since the real clock moves on between requests rather than
inside one.
"""

from __future__ import annotations

import time

from app.db import cursor
from app.pending import FORGET_UNVERIFIED_SECONDS, SETTLE_SECONDS, PendingRegistry

NS = "utest0000000001"
OTHER_NS = "utest0000000002"


def _registry_with(kind="note", preview="a note", store_result=None, namespace=NS):
    reg = PendingRegistry()
    item = reg.add(
        namespace=namespace,
        kind=kind,
        preview=preview,
        batch_id="b1",
        store_result=store_result or {},
    )
    return reg, item


def _backdate(item_id: str, *, created_at=None, verified_at=None) -> None:
    """Age a write, the way the clock would have."""
    with cursor(commit=True) as cur:
        if created_at is not None:
            cur.execute(
                "UPDATE pending_writes SET created_at = %s WHERE id = %s", (created_at, item_id)
            )
        if verified_at is not None:
            cur.execute(
                "UPDATE pending_writes SET verified_at = %s WHERE id = %s", (verified_at, item_id)
            )


def test_async_write_starts_as_indexing():
    _, item = _registry_with(store_result={"pending_id": "tmp_1", "stored": False})
    assert item.status == "indexing"


def test_sync_write_is_recorded_as_measured_not_assumed():
    """A synchronous store came back already persisted — there is nothing to wait
    for, so it is 'indexed' on evidence rather than on a timer."""
    _, item = _registry_with(store_result={"episode_id": "ep1", "stored": True})
    assert item.status == "indexed"
    assert item.verified_at is not None


def test_becomes_likely_indexed_after_the_settle_window():
    reg, item = _registry_with(store_result={"pending_id": "tmp_1", "stored": False})
    _backdate(item.id, created_at=time.time() - (SETTLE_SECONDS + 5))
    assert reg.list(NS)[0].status == "likely_indexed"


def test_a_timer_never_promotes_to_indexed():
    """`likely_indexed` is a guess and `indexed` is a measurement. Only an
    explicit check that actually looked may cross that line."""
    reg, item = _registry_with(store_result={"pending_id": "tmp_1", "stored": False})
    _backdate(item.id, created_at=time.time() - (SETTLE_SECONDS + 5))
    assert all(i.status != "indexed" for i in reg.list(NS))

    reg.mark_verified(NS, item.id, found=True)
    assert reg.get(NS, item.id).status == "indexed"


def test_stale_unverified_writes_leave_the_tray():
    """Regression: a nine-minute-old pill kept putting 'still settling' on every
    answer. Past the server's buffer lifetime the claim is no longer true."""
    reg, item = _registry_with(store_result={"pending_id": "tmp_1", "stored": False})
    _backdate(item.id, created_at=time.time() - (FORGET_UNVERIFIED_SECONDS + 10))

    assert reg.list(NS) == []
    assert reg.unsettled_count(NS) == 0


def test_verified_writes_clear_shortly_after_going_green():
    reg, item = _registry_with(store_result={"pending_id": "tmp_1", "stored": False})
    reg.mark_verified(NS, item.id, found=True)
    assert len(reg.list(NS)) == 1

    _backdate(item.id, verified_at=time.time() - 45)
    assert reg.list(NS) == []


def test_unsettled_count_drives_the_answer_caveat():
    reg, _ = _registry_with(store_result={"pending_id": "tmp_1", "stored": False})
    assert reg.unsettled_count(NS) == 1
    reg.add(
        namespace=NS,
        kind="photo",
        preview="a photo",
        batch_id="b2",
        store_result={"pending_id": "tmp_2", "stored": False},
    )
    assert reg.unsettled_count(NS) == 2


def test_verifying_an_unknown_id_is_harmless():
    reg, _ = _registry_with(store_result={"pending_id": "tmp_1", "stored": False})
    assert reg.mark_verified(NS, "nope", found=True) is None


def test_one_account_never_sees_another_accounts_tray():
    """Regression, and the reason this module was rewritten.

    The registry was a single process-wide dict with no namespace in it, so
    `GET /api/pending` returned every account's in-flight writes — `preview`
    included, which is the first 120 characters of whatever they had just
    typed. The chat screen polls that endpoint every few seconds.
    """
    reg, mine = _registry_with(preview="my private note")
    reg.add(
        namespace=OTHER_NS,
        kind="note",
        preview="somebody else's note",
        batch_id="b9",
        store_result={"pending_id": "tmp_9", "stored": False},
    )

    mine_only = reg.list(NS)
    assert [i.preview for i in mine_only] == ["my private note"]
    assert reg.unsettled_count(NS) == 1

    # And the id alone is not enough to reach across the boundary.
    assert reg.get(OTHER_NS, mine.id) is None
    assert reg.mark_verified(OTHER_NS, mine.id, found=True) is None
