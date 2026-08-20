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


def test_every_real_message_retrieves_memory(stubbed):
    """The old path only searched when a regex saw a question mark, so anything
    phrased without one was answered blind."""
    client, headers = _signed_in()
    client.post("/api/converse", json={"message": "where did I put the keys"}, headers=headers)

    assert stubbed["retrieved"] == ["where did I put the keys"]


def test_a_greeting_costs_nothing(stubbed):
    """Neither a retrieval nor a write. Nothing in the graph answers "hey", and
    waiting on Reeve to find that out is three seconds of nothing."""
    client, headers = _signed_in()
    client.post("/api/converse", json={"message": "hey"}, headers=headers)

    assert stubbed["retrieved"] == []
    assert stubbed["stored"] == []


# ── what gets kept ────────────────────────────────────────────────────────────


def test_a_statement_is_stored(stubbed):
    client, headers = _signed_in()
    stubbed["intent"] = "remember"
    response = client.post(
        "/api/converse", json={"message": "The seminar moved to room 214."}, headers=headers
    )

    assert _events(response)[-1][1]["stored"] is True
    assert stubbed["stored"] == ["The seminar moved to room 214."]


def test_a_pure_question_is_not_promoted_to_the_graph(stubbed):
    """Nobody ever retrieves "what did I ask about my locker code", and every
    stored question competes for the few slots retrieval returns — which is how
    a signed-in user got told his name was unknown. The text still lives in the
    conversation transcript, so this decision costs nothing if it is wrong."""
    client, headers = _signed_in()
    stubbed["context"] = "The seminar is in room 210."
    response = client.post(
        "/api/converse", json={"message": "where is the seminar"}, headers=headers
    )

    assert _events(response)[-1][1]["stored"] is False
    assert stubbed["stored"] == []


def test_a_question_carrying_a_fact_is_promoted_whole(stubbed):
    """Splitting a mixed message to keep half of it would be worse than keeping
    the question alongside the fact."""
    client, headers = _signed_in()
    client.post(
        "/api/converse",
        json={"message": "where is the seminar? it moved to 214"},
        headers=headers,
    )

    assert stubbed["stored"] == ["where is the seminar? it moved to 214"]


@pytest.mark.parametrize(
    "message",
    ["what is my name", "how old is she?", "where did I put it", "who is Marta?"],
)
def test_questions_are_recognised_without_a_model(message):
    from app.routes.converse import _is_only_a_question

    assert _is_only_a_question(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "my locker code is 4417",
        "she is aleyna, a 20 year old girl",
        "the seminar moved to room 214",
        "will call Marta tomorrow about the fieldwork",
        "can meet Marta at five",
        "do you remember the code",
    ],
)
def test_statements_are_never_mistaken_for_questions(message):
    """The cost of a false positive is a lost memory; the cost of a false
    negative is one wasted slot. So only a question mark or an opening wh-word
    counts. Auxiliaries were tried and removed: "will call Marta tomorrow" and
    "can meet Marta at five" are notes that open like questions. The price is
    that an unpunctuated "do you remember the code" gets promoted, which is the
    cheaper mistake."""
    from app.routes.converse import _is_only_a_question

    assert _is_only_a_question(message) is False


def test_chat_with_content_is_kept(stubbed):
    """"thanks, that helps" carries a word that is not a pleasantry, so it is
    kept. Only messages made entirely of pleasantries are ignored."""
    client, headers = _signed_in()
    stubbed["intent"] = "chat"
    client.post("/api/converse", json={"message": "thanks, that helps"}, headers=headers)

    assert stubbed["stored"] == ["thanks, that helps"]


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


# ── what counts as a greeting ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "message",
    ["hey", "hey there", "hello!", "good morning", "thanks", "thank you", "ok cool", "👍"],
)
def test_greetings_are_ignored(message):
    """Not stored and not made to wait for memory: "hey" is not a memory, and
    nothing in the graph answers it."""
    from app.routes.converse import _is_greeting

    assert _is_greeting(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "she is aleyna , a 20 year old girl",
        "hey my locker code is 4417",
        "no, the seminar moved to 214",
        "yes I live in Pune",
        "what is my name",
    ],
)
def test_anything_with_content_is_kept(message):
    """The shape-based heuristic this replaced — short, no question mark,
    nothing about the speaker — matched "she is aleyna" and threw it away."""
    from app.routes.converse import _is_greeting

    assert _is_greeting(message) is False


def test_every_non_greeting_is_stored(stubbed):
    """No judgement call about what deserves keeping. The classifier calling a
    fact "small talk" is how "Got it — Aleyna, 20" was said over an empty
    write."""
    client, headers = _signed_in()
    stubbed["intent"] = "chat"
    response = client.post(
        "/api/converse", json={"message": "she is aleyna, a 20 year old girl"}, headers=headers
    )

    assert _events(response)[-1][1]["stored"] is True
    assert stubbed["stored"] == ["she is aleyna, a 20 year old girl"]


def test_a_greeting_is_not_stored(stubbed):
    client, headers = _signed_in()
    stubbed["intent"] = "chat"
    response = client.post("/api/converse", json={"message": "hey there"}, headers=headers)

    assert _events(response)[-1][1]["stored"] is False
    assert stubbed["stored"] == []


# ── persona ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "message",
    [
        "you are aleyna, a 20 year old girl",
        "you're Aleyna",
        "your name is Aleyna",
        "from now on you are Aleyna",
        "act as a patient tutor",
    ],
)
def test_persona_statements_are_marked_as_being_about_the_assistant(message):
    """Stored as plain text these read as notes about a third person, which is
    exactly what went wrong: asked later it said "She's 20" instead of "I'm 20",
    and a fresh session said it had no name at all."""
    assert conversation.is_persona(message)
    assert conversation.as_memory(message).startswith(conversation.PERSONA_PREFIX)


@pytest.mark.parametrize(
    "message",
    [
        "she is aleyna, a 20 year old girl",
        "my sister is 20",
        "aleyna is my lab partner",
        "the seminar moved to room 214",
    ],
)
def test_facts_about_other_people_are_stored_as_written(message):
    """A persona marker on a note about somebody else would make the assistant
    answer as them, which is worse than the bug it fixes."""
    assert not conversation.is_persona(message)
    assert conversation.as_memory(message) == message


def test_the_persona_marker_reaches_the_graph(stubbed):
    client, headers = _signed_in()
    client.post("/api/converse", json={"message": "you are Aleyna"}, headers=headers)

    assert stubbed["stored"] == [f"{conversation.PERSONA_PREFIX}you are Aleyna"]


# ── identity is not retrieved ─────────────────────────────────────────────────


def test_the_signed_in_name_is_always_stated(stubbed, monkeypatch):
    """Asked "who am I", retrieval once returned a top-K without the line naming
    the person, so it answered "you haven't told me your name yet" — and the
    next message, phrased differently, got it right. The name is on the account;
    it must never depend on ranking luck."""
    seen = {}

    def capture(**kwargs):
        seen.update(kwargs)
        return iter(["ok"])

    import app.routes.converse as route

    monkeypatch.setattr(route.conversation, "stream_reply", capture)
    session = auth.register("ada@example.com", "a good password", "Ada Lovelace")
    client = TestClient(app)
    client.post(
        "/api/converse",
        json={"message": "who am i"},
        headers={"Authorization": f"Bearer {session['token']}"},
    )

    assert seen["speaker_name"] == "Ada Lovelace"


def test_a_persona_is_saved_to_the_account_immediately(stubbed):
    """Not in a background task: the next message can arrive before a background
    write lands, and being someone else for one turn is the bug."""
    session = auth.register("ada@example.com", "a good password", "Ada")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {session['token']}"}

    client.post("/api/converse", json={"message": "you are Mira"}, headers=headers)

    assert auth.resolve(session["token"])["persona"] == "you are Mira"


# ── persona detection must not fire on ordinary remarks ───────────────────────


@pytest.mark.parametrize(
    "message",
    [
        "you are Mira, a librarian",
        "you are a patient tutor",
        "your name is Otto",
        "from now on you are a study coach",
        "act as a study coach",
        "pretend to be my lab partner",
    ],
)
def test_real_persona_assignments_are_caught(message):
    assert conversation.is_persona(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "You are my ?",        # found in production: a half-typed question, stored as a persona
        "you are wrong",
        "you are so slow",
        "you're annoying",
        "you are the best",
        "what are you doing?",
        "I think you are great",
        "the seminar moved to room 214",
    ],
)
def test_remarks_and_questions_are_not_personas(message):
    """A persona is injected into every prompt from then on and silently
    replaces whatever the person actually chose, so a false positive is worse
    than a miss: missing costs a retype, catching wrongly leaves an assistant
    that has quietly become "so slow". "You are my ?" is not hypothetical — it
    was sitting in a production account's persona column."""
    assert conversation.is_persona(message) is False
