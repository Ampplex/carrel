"""Settling-tray tests. Zero quota.

The tray is the app's honesty device, so its two failure modes are both bad in
opposite directions: forget a write too early and an answer looks more complete
than it is; keep one forever and every answer carries a warning nobody believes.
"""

from __future__ import annotations

import time

from app.pending import FORGET_UNVERIFIED_SECONDS, SETTLE_SECONDS, PendingRegistry


def _registry_with(kind="note", preview="a note", store_result=None):
    reg = PendingRegistry()
    item = reg.add(kind=kind, preview=preview, batch_id="b1", store_result=store_result or {})
    return reg, item


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
    reg._items[item.id].created_at = time.time() - (SETTLE_SECONDS + 5)
    assert reg.list()[0].status == "likely_indexed"


def test_a_timer_never_promotes_to_indexed():
    """`likely_indexed` is a guess and `indexed` is a measurement. Only an
    explicit check that actually looked may cross that line."""
    reg, item = _registry_with(store_result={"pending_id": "tmp_1", "stored": False})
    reg._items[item.id].created_at = time.time() - (SETTLE_SECONDS + 5)
    assert all(i.status != "indexed" for i in reg.list())

    reg.mark_verified(item.id, found=True)
    assert reg.get(item.id).status == "indexed"


def test_stale_unverified_writes_leave_the_tray():
    """Regression: a nine-minute-old pill kept putting 'still settling' on every
    answer. Past the server's buffer lifetime the claim is no longer true."""
    reg, item = _registry_with(store_result={"pending_id": "tmp_1", "stored": False})
    reg._items[item.id].created_at = time.time() - (FORGET_UNVERIFIED_SECONDS + 10)

    assert reg.list() == []
    assert reg.unsettled_count() == 0


def test_verified_writes_clear_shortly_after_going_green():
    reg, item = _registry_with(store_result={"pending_id": "tmp_1", "stored": False})
    reg.mark_verified(item.id, found=True)
    assert len(reg.list()) == 1

    reg._items[item.id].verified_at = time.time() - 45
    assert reg.list() == []


def test_unsettled_count_drives_the_answer_caveat():
    reg, _ = _registry_with(store_result={"pending_id": "tmp_1", "stored": False})
    assert reg.unsettled_count() == 1
    reg.add(kind="photo", preview="a photo", batch_id="b2",
            store_result={"pending_id": "tmp_2", "stored": False})
    assert reg.unsettled_count() == 2


def test_verifying_an_unknown_id_is_harmless():
    reg, _ = _registry_with(store_result={"pending_id": "tmp_1", "stored": False})
    assert reg.mark_verified("nope", found=True) is None
