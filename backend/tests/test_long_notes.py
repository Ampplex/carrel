"""Storing a lot of text at once. Zero quota — Reeve is stubbed.

The old ceiling was twelve chunks, about 7,200 characters, past which a note was
refused with "break it up yourself". The count was never the real constraint:
writes are paced to avoid throttling upstream, so the request stayed open for
roughly two seconds per chunk. Raising the count without moving the work off the
request would only have traded a refusal for a timeout.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app import auth, reeve_gateway
from app.chunking import chunk_note
from app.config import settings
from app.main import app
from app.pending import registry


@pytest.fixture(autouse=True)
def no_pacing():
    """Settings is a frozen dataclass — frozen on purpose, so configuration
    cannot change under a running server. Tests reach past it and put it back."""
    previous = settings.chunk_pace_seconds
    object.__setattr__(settings, "chunk_pace_seconds", 0)
    yield
    object.__setattr__(settings, "chunk_pace_seconds", previous)


@pytest.fixture
def stub_reeve(monkeypatch):
    """Record what would have been written, instantly."""
    written: list[str] = []

    def fake_store(text, namespace):
        written.append(text)
        return {"stored": True}

    import app.routes.capture as capture

    monkeypatch.setattr(capture.reeve_gateway, "store_note", fake_store)
    monkeypatch.setattr(reeve_gateway, "store_note", fake_store)
    return written


def _signed_in() -> tuple[TestClient, dict]:
    session = auth.register("ada@example.com", "a good password")
    client = TestClient(app)
    return client, {"Authorization": f"Bearer {session['token']}"}


def _long_text(chars: int) -> str:
    para = "Consistency models were compared in detail during the seminar today. "
    body = (para * ((chars // len(para)) + 1))[:chars]
    return "\n\n".join(body[i : i + 500] for i in range(0, len(body), 500))


def test_a_note_far_past_the_old_ceiling_is_accepted(stub_reeve):
    """~30,000 characters — four times what the old limit allowed."""
    client, headers = _signed_in()

    response = client.post(
        "/api/notes", json={"text": _long_text(30_000)}, headers=headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["chunked"] is True
    assert len(body["pending"]) > 12, "the old ceiling would have refused this"


def test_the_writes_are_scheduled_rather_than_run_inline(stub_reeve, monkeypatch):
    """The point of the change — but not something TestClient can time.

    TestClient runs background tasks as part of the request cycle, so a wall
    clock here measures the work happening either way. What it *can* check is
    the mechanism: the route hands the writing to a background task instead of
    calling Reeve in the request body. The timing itself was verified against
    the deployed server, where the response returns before any write starts.
    """
    import app.routes.capture as capture

    scheduled: list = []
    original = capture.BackgroundTasks.add_task

    def record(self, func, *args, **kwargs):
        scheduled.append(func.__name__)
        return original(self, func, *args, **kwargs)

    monkeypatch.setattr(capture.BackgroundTasks, "add_task", record)
    client, headers = _signed_in()

    client.post("/api/notes", json={"text": _long_text(20_000)}, headers=headers)

    assert scheduled == ["_write_chunks"], scheduled


def test_every_chunk_is_actually_written(stub_reeve):
    """Accepting text and then dropping some of it would be worse than refusing
    it, because nothing would say so."""
    client, headers = _signed_in()
    text = _long_text(12_000)

    response = client.post("/api/notes", json={"text": text}, headers=headers)
    expected = len(chunk_note(text))

    assert len(response.json()["pending"]) == expected
    # TestClient runs background tasks before returning, so by here they are done.
    assert len(stub_reeve) == expected


def test_an_accepted_but_unsettled_write_is_not_called_a_failure(monkeypatch):
    """The bug this caught in production.

    Reeve answers an asynchronous write with `stored: False` and a pending id,
    meaning *accepted, still settling* — which is the entire reason this tray
    exists. Reading that as failure marked 58 chunks of a perfectly good note as
    `failed`, with no errors logged anywhere, because nothing had gone wrong.
    """
    import app.routes.capture as capture

    monkeypatch.setattr(
        capture.reeve_gateway,
        "store_note",
        lambda text, namespace: {"stored": False, "pending_id": "tmp_1"},
    )

    session = auth.register("ada@example.com", "a good password")
    client = TestClient(app)
    client.post(
        "/api/notes",
        json={"text": _long_text(4_000)},
        headers={"Authorization": f"Bearer {session['token']}"},
    )

    statuses = {item.status for item in registry.list(session["namespace"])}
    assert statuses == {"indexing"}, statuses
    assert "failed" not in statuses


def test_a_failed_chunk_is_marked_rather_than_left_looking_busy(monkeypatch):
    """An entry stuck on 'indexing' ages out of the tray in five minutes and
    takes the bad news with it."""
    import app.routes.capture as capture

    calls = {"n": 0}

    def flaky(text, namespace):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("reeve said no")
        return {"stored": True}

    monkeypatch.setattr(capture.reeve_gateway, "store_note", flaky)

    session = auth.register("ada@example.com", "a good password")
    client = TestClient(app)
    client.post(
        "/api/notes",
        json={"text": _long_text(4_000)},
        headers={"Authorization": f"Bearer {session['token']}"},
    )

    statuses = [item.status for item in registry.list(session["namespace"])]
    assert "failed" in statuses, statuses
    assert "indexed" in statuses, "the chunks either side should have gone through"


def test_something_absurd_is_still_refused(stub_reeve):
    """The ceiling moved; it did not disappear. A refusal that explains itself
    beats accepting a megabyte and silently keeping part of it."""
    client, headers = _signed_in()

    response = client.post(
        "/api/notes", json={"text": _long_text(settings.max_chunks * 700 + 20_000)}, headers=headers
    )

    assert response.status_code == 413
    assert str(settings.max_chunks) in response.json()["detail"]
