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


# Classification used to live here — a small extra model call that labelled each
# message remember / ask / chat. It is gone. Keeping every message removed the
# decision it existed to make, and a judgement call that can be wrong has no
# business sitting in front of "did you keep this or not": it once answered
# "small talk" to a plain statement of fact, so the reply said "Got it" over a
# write that never happened.


# A message like "you are Mira, a 26 year old librarian" is not a note about
# somebody called Mira. It is an instruction about who the assistant is, and
# stored as plain text it comes back looking like a third person — which is why
# asking later got "She's 26" instead of "I'm 26", and why a fresh session said
# it had no name or age at all. Marking it at write time is what makes it
# unambiguous when retrieved months later, beside everything else they said.
_PERSONA = re.compile(
    r"\b(you are|you're|youre|your name is|call yourself|act as|"
    r"pretend to be|behave like|from now on you)\b",
    re.IGNORECASE,
)

PERSONA_PREFIX = "Persona the user set for you (this describes YOU, the assistant, not another person): "


def is_persona(message: str) -> bool:
    return bool(_PERSONA.search(message))


def as_memory(message: str) -> str:
    """What actually gets written to the graph for this message."""
    return f"{PERSONA_PREFIX}{message}" if is_persona(message) else message


SYSTEM_PROMPT = """\
You are Carrel, the person's own memory. You talk like a person, not a database.

WHO YOU ARE
Carrel is only your default name. If MEMORIES contains a persona the person set
for you — a name, an age, a character — then that is who you are: answer to that
name, speak as them in the first person, and never describe that persona in the
third person as if it were somebody else. A persona changes your voice and
nothing else; every rule below still holds. Stay inside what the persona
actually says, too — a name and an age are a name and an age, not a licence to
invent a job, a street or a history that nobody gave you.

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
4a. MEMORIES is there to answer with, not to recite. Do not bring one up that \
was not asked about. If they say hello, say hello back and stop — do not \
mention what they stored earlier, and do not ask whether a memory is still \
relevant.
4b. Never say when something happened, or that it was recent, unless a memory \
says so. "Earlier", "just now" and "the other day" are claims about time and \
they need a source like any other fact.
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
