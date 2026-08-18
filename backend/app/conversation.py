"""The conversation layer: Mistral on Bedrock, streamed, grounded in Reeve.

Before this, Carrel had exactly two behaviours. A message was classified by
regex as a question or a statement; a question went to Reeve and came back as
one flat sentence, a statement was swallowed with the word "Remembered." That
is a competent memory tool and a poor conversation — you could not say "thanks",
could not ask a follow-up that referred to the previous answer, and every reply
arrived all at once after a silence long enough to wonder whether it had failed.

Three things change here, and they are separable on purpose:

**Every message goes through memory.** Not just the ones a regex thought were
questions. Retrieval happens first, always, and what comes back is offered to
the model as context. A greeting retrieves nothing and costs one cheap call; a
question about a room number retrieves the room number.

**The model decides what is worth keeping**, not a pattern. "The seminar moved
to 214" is a fact about the user's world and is stored; "what did I just say?"
is not; "thanks, that helps" is not. A regex cannot tell those apart, and the
old one didn't — it stored questions whenever they lacked a question mark, and
polluted the graph with them.

**Nothing found is not an error.** The old path answered "I don't remember",
which is honest and sounds like a machine reporting a lookup miss. A person
says "you haven't told me that yet". The distinction that matters is not tone
but truth: the model may talk about anything, and may never assert a fact about
this user's life that is not in the retrieved context. Those are different
rules, and the prompt states them separately.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Iterator, Literal

import boto3
from botocore.config import Config as BotoConfig

from app.config import settings

logger = logging.getLogger(__name__)

Intent = Literal["remember", "ask", "chat"]

# One client for the process. Creating a boto3 client costs tens of milliseconds
# and opens a fresh connection pool; on a chat endpoint that is per-keystroke
# latency for no reason.
_client = None


def _runtime():
    global _client
    if _client is None:
        _client = boto3.client(
            "bedrock-runtime",
            region_name=settings.chat_region,
            config=BotoConfig(
                retries={"max_attempts": 2, "mode": "standard"},
                # A streamed reply holds the socket open for as long as it takes
                # to write the answer, so the read timeout has to cover the whole
                # reply rather than one round trip.
                read_timeout=120,
                connect_timeout=10,
            ),
        )
    return _client


CLASSIFY_PROMPT = """\
You sort one message from a person into exactly one of three kinds. Answer with \
one word and nothing else.

remember - the message states something about their own life, work or plans that \
is worth keeping: a fact, a decision, a change of plan, a person, a place, a \
deadline. Corrections count ("actually it moved to Thursday").
ask - the message asks for something they have told this app before.
chat - anything else: greetings, thanks, small talk, questions about the world \
that have nothing to do with their own stored life, and questions about this \
conversation itself.

Message: {message}"""


def classify(message: str) -> Intent:
    """Which of the three things is this message doing?

    Kept as its own tiny call rather than folded into the streamed reply. The
    alternative — asking the model to emit a marker line and then the answer —
    means either showing the marker to the user or buffering the stream until it
    can be stripped, and buffering is exactly what streaming exists to avoid.
    """
    try:
        response = _runtime().converse(
            modelId=settings.chat_model_id,
            messages=[{"role": "user", "content": [{"text": CLASSIFY_PROMPT.format(message=message)}]}],
            inferenceConfig={"maxTokens": 5, "temperature": 0},
        )
        word = _text_of(response).strip().lower()
    except Exception as exc:
        # Never fail the message over classification. Treating an unknown as
        # "ask" keeps the memory path working, which is the part people notice.
        logger.warning("classification failed, defaulting to ask: %s", exc)
        return "ask"

    if word.startswith("remember"):
        return "remember"
    if word.startswith("chat"):
        return "chat"
    return "ask"


SYSTEM_PROMPT = """\
You are Carrel, the person's own memory. You talk like a person, not a database.

WHAT YOU KNOW
The MEMORIES block below is everything this person has told you that relates to \
their message. It may be empty. It is the only source you have about their life.

RULES
1. Answer conversationally, in one to three sentences unless more is genuinely \
needed. No preamble, no restating the question, no offers to help further.
2. Anything about THIS PERSON — their plans, rooms, deadlines, people, \
belongings, photographs — must come from MEMORIES. Never guess at it, never \
fill a gap with something plausible.
3. If they ask about their own life and MEMORIES does not contain it, say so \
the way a person would: they have not mentioned it to you yet. Do not say "I \
don't remember", and do not apologise at length.
4. General knowledge, advice, and ordinary conversation are yours to answer \
normally, with no reference to memories at all.
5. When a memory contradicts an older one, the later one is what is true now. \
Say what is true now; mention the change only if it is what they asked about.
6. When they have just told you something, acknowledge it briefly and naturally \
in your own words. Never say "Remembered."
7. Plain sentences. No markdown, no bullet points, no headings.

MEMORIES
{memories}"""


def _text_of(response: dict) -> str:
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    return "".join(b.get("text", "") for b in blocks if isinstance(b, dict))


def _history_messages(history: list[dict]) -> list[dict]:
    """Turn stored chat rows into Bedrock messages, newest last.

    Bedrock rejects a conversation that does not alternate strictly, and a
    stored thread can easily contain two user rows in a row (someone typed twice
    before the answer landed). Merging rather than dropping keeps what they said.
    """
    turns: list[dict] = []
    for row in history[-settings.chat_history_turns :]:
        role = "user" if row.get("role") == "you" else "assistant"
        text = (row.get("text") or "").strip()
        if not text:
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"][0]["text"] += "\n" + text
        else:
            turns.append({"role": role, "content": [{"text": text}]})
    # A conversation must open with the user, or Bedrock refuses it.
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    return turns


def stream_reply(
    *, message: str, memories: str, history: list[dict] | None = None
) -> Iterator[str]:
    """Yield the reply in pieces, as the model writes it."""
    system = SYSTEM_PROMPT.format(memories=memories.strip() or "(nothing stored about this yet)")
    messages = _history_messages(history or [])
    messages.append({"role": "user", "content": [{"text": message}]})

    response = _runtime().converse_stream(
        modelId=settings.chat_model_id,
        system=[{"text": system}],
        messages=messages,
        inferenceConfig={"maxTokens": 700, "temperature": 0.4},
    )
    for event in response["stream"]:
        delta = event.get("contentBlockDelta", {}).get("delta", {})
        piece = delta.get("text")
        if piece:
            yield piece


# Some Mistral builds still open a reply with a courtesy line before the answer.
# Cheap to strip, and it is the difference between an answer and a preamble.
_OPENER = re.compile(r"^(sure|certainly|of course|absolutely)[,!.]?\s+", re.IGNORECASE)


def strip_opener(first_chunk: str) -> str:
    return _OPENER.sub("", first_chunk, count=1)


def sse(event: str, **data) -> bytes:
    """One server-sent event. Newline-delimited JSON inside the SSE envelope so
    the client never has to guess where a message ends."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()
