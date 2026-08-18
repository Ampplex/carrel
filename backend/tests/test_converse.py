"""The conversation endpoint: classify, retrieve, stream, then store.

Nothing here talks to Bedrock or to Reeve. What is being pinned is the wiring
and the order of it — which is where this endpoint can go wrong in ways that are
invisible in a demo:

  * a statement that never gets stored, because the reply looked fine
  * a store that runs before the reply and delays every word of it
  * an evidence panel under a greeting, which teaches people it means nothing
  * a classification failure taking the whole message down with it
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import auth, conversation, reeve_gateway
from app.main import app


@pytest.fixture
def stubbed(monkeypatch):
    """A conversation with no network in it."""
    state = {"stored": [], "retrieved": [], "intent": "chat", "reply": ["Hello ", "there."]}

    def fake_context(question, namespace):
        state["retrieved"].append(question)
        return state.get("context", "")

    def fake_store(text, namespace):
        state["stored"].append(text)
        return {"stored": True}

    import app.routes.converse as route

    monkeypatch.setattr(route.reeve_gateway, "context", fake_context)
    monkeypatch.setattr(route.reeve_gateway, "store_note", fake_store)
    monkeypatch.setattr(reeve_gateway, "store_note", fake_store)
    monkeypatch.setattr(route.conversation, "classify", lambda message: state["intent"])
    monkeypatch.setattr(
        route.conversation,
        "stream_reply",
        lambda **kwargs: iter(state["reply"]),
    )
    return state


def _signed_in(email="ada@example.com") -> tuple[TestClient, dict]:
    session = auth.register(email, "a good password")
    return TestClient(app), {"Authorization": f"Bearer {session['token']}"}


def _events(response) -> list[tuple[str, dict]]:
    out = []
    for block in response.text.split("\n\n"):
        if not block.strip():
            continue
        kind = payload = None
        for line in block.splitlines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                payload = json.loads(line[6:])
        if kind:
            out.append((kind, payload or {}))
    return out


# ── the shape of a reply ──────────────────────────────────────────────────────


def test_streams_meta_then_tokens_then_done(stubbed):
    client, headers = _signed_in()
    response = client.post("/api/converse", json={"message": "hello"}, headers=headers)

    kinds = [kind for kind, _ in _events(response)]
    assert kinds[0] == "meta"
    assert kinds[-1] == "done"
    assert kinds.count("token") == 2

    done = _events(response)[-1][1]
    assert done["answer"] == "Hello there."


def test_every_message_retrieves_memory_even_a_greeting(stubbed):
    """The old path only searched when a regex saw a question mark. A greeting
    costs one cheap retrieval; a missed one costs an answer."""
    client, headers = _signed_in()
    stubbed["intent"] = "chat"
    client.post("/api/converse", json={"message": "hey"}, headers=headers)

    assert stubbed["retrieved"] == ["hey"]


# ── what gets kept ────────────────────────────────────────────────────────────


def test_a_statement_is_stored(stubbed):
    client, headers = _signed_in()
    stubbed["intent"] = "remember"
    response = client.post(
        "/api/converse", json={"message": "The seminar moved to room 214."}, headers=headers
    )

    assert _events(response)[-1][1]["stored"] is True
    assert stubbed["stored"] == ["The seminar moved to room 214."]


def test_a_question_is_not_stored(stubbed):
    """Storing questions is how a memory graph fills up with things nobody
    said. The old regex did exactly this whenever a question lacked its mark."""
    client, headers = _signed_in()
    stubbed["intent"] = "ask"
    stubbed["context"] = "The seminar is in room 210."
    response = client.post(
        "/api/converse", json={"message": "where is the seminar"}, headers=headers
    )

    assert _events(response)[-1][1]["stored"] is False
    assert stubbed["stored"] == []


def test_chat_is_not_stored(stubbed):
    client, headers = _signed_in()
    stubbed["intent"] = "chat"
    client.post("/api/converse", json={"message": "thanks, that helps"}, headers=headers)

    assert stubbed["stored"] == []


# ── sources ───────────────────────────────────────────────────────────────────


def test_evidence_only_where_memory_was_used(stubbed):
    client, headers = _signed_in()
    stubbed["intent"] = "ask"
    stubbed["context"] = "FACTS:\n- the seminar is in room 210\n"
    response = client.post("/api/converse", json={"message": "where?"}, headers=headers)

    assert _events(response)[-1][1]["evidence"] is not None


def test_no_evidence_panel_under_small_talk(stubbed):
    client, headers = _signed_in()
    stubbed["intent"] = "chat"
    stubbed["context"] = "FACTS:\n- something unrelated\n"
    response = client.post("/api/converse", json={"message": "good morning"}, headers=headers)

    assert _events(response)[-1][1]["evidence"] is None


# ── failure ───────────────────────────────────────────────────────────────────


def test_retrieval_failure_still_answers(stubbed, monkeypatch):
    """Reeve being down should cost memory, not the conversation."""
    import app.routes.converse as route

    def boom(question, namespace):
        raise RuntimeError("reeve is down")

    monkeypatch.setattr(route.reeve_gateway, "context", boom)
    client, headers = _signed_in()
    response = client.post("/api/converse", json={"message": "hello"}, headers=headers)

    assert _events(response)[-1][1]["answer"] == "Hello there."


def test_model_failure_is_reported_not_swallowed(stubbed, monkeypatch):
    import app.routes.converse as route

    def boom(**kwargs):
        raise RuntimeError("bedrock refused")
        yield  # pragma: no cover - generator shape

    monkeypatch.setattr(route.conversation, "stream_reply", boom)
    client, headers = _signed_in()
    response = client.post("/api/converse", json={"message": "hello"}, headers=headers)

    kinds = [kind for kind, _ in _events(response)]
    assert "error" in kinds
    assert "done" not in kinds


# ── the model layer, without a model ──────────────────────────────────────────


@pytest.mark.parametrize(
    "word,expected",
    [
        ("remember", "remember"),
        ("Remember.", "remember"),
        ("ask", "ask"),
        ("chat", "chat"),
        ("CHAT", "chat"),
        ("something else entirely", "ask"),
    ],
)
def test_classify_reads_the_models_word(monkeypatch, word, expected):
    monkeypatch.setattr(
        conversation,
        "_runtime",
        lambda: type(
            "R",
            (),
            {
                "converse": staticmethod(
                    lambda **kw: {"output": {"message": {"content": [{"text": word}]}}}
                )
            },
        )(),
    )
    assert conversation.classify("anything") == expected


def test_classify_failure_defaults_to_ask(monkeypatch):
    """The memory path is the one people notice missing, so an unclassifiable
    message is treated as a question rather than dropped or stored."""

    def boom():
        raise RuntimeError("no bedrock")

    monkeypatch.setattr(conversation, "_runtime", boom)
    assert conversation.classify("anything") == "ask"


def test_history_alternates_and_opens_with_the_user():
    """Bedrock rejects a conversation that does not strictly alternate, and a
    stored thread can hold two user rows in a row when someone typed twice
    before the answer landed."""
    turns = conversation._history_messages(
        [
            {"role": "Carrel", "text": "orphaned opening"},
            {"role": "you", "text": "first"},
            {"role": "you", "text": "second"},
            {"role": "Carrel", "text": "reply"},
            {"role": "you", "text": ""},
        ]
    )

    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert turns[0]["content"][0]["text"] == "first\nsecond"


def test_opener_is_stripped_once():
    assert conversation.strip_opener("Sure, room 210.") == "room 210."
    assert conversation.strip_opener("Certainly! it moved.") == "it moved."
    assert conversation.strip_opener("Room 210, surely.") == "Room 210, surely."
