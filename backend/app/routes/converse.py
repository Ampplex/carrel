"""One endpoint for talking to Carrel.

`POST /api/converse` replaces the old split between "ask" and "store": the
client sends whatever the person typed and gets back a stream of server-sent
events. Deciding what the message *was* now happens here, with a model, rather
than in the app with a regex over question marks.

The order of work is the part worth reading.

    retrieve  ──► always, for every message, in parallel with
    classify  ──► which needs no memory and finishes first
    stream    ──► the reply, in pieces, as it is written
    store     ──► after the reply, in the background, if it was worth keeping

Whether generation waits for retrieval depends on what the message turned out
to be, and that asymmetry was measured rather than assumed: retrieval takes
about 3.7 seconds, and blocking every message on it meant that long staring at
nothing before the first character. For a question that wait is the product —
the answer IS the memory, and a fast wrong answer is worse than a slow right
one. For "hey there" it bought nothing at all, so small talk starts writing
immediately and uses the memories only if they happen to arrive in time.

Storing waits until the reply has been streamed, so a paced write never delays
a word of it, and it goes through the same pending registry as every other
write, so the "still settling" caveat keeps working exactly as before.

There is one rule inherited from the rest of this codebase and it still holds:
never two Reeve calls at once for a single user action. Retrieval runs alone;
the store that may follow runs after the response is finished.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse

from app import auth, chats, conversation, quota, reeve_gateway
from app.chunking import chunk_note
from app.models import ConverseIn
from app.parsers.context_parser import parse_context
from app.pending import registry

router = APIRouter()
log = logging.getLogger("carrel.converse")

# Two slots per request: retrieval and classification. Shared, because a pool
# per request costs more than the overlap it buys.
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="carrel-converse")


@router.post("/api/converse")
def converse(
    payload: ConverseIn,
    background: BackgroundTasks,
    user: dict = Depends(auth.current_user),
) -> StreamingResponse:
    ns = user["namespace"]
    message = payload.message.strip()
    started = time.monotonic()

    history = []
    if payload.chat_id:
        thread = chats.get(ns, payload.chat_id)
        if thread:
            history = thread.get("messages", [])

    def events():
        if not message:
            yield conversation.sse("done", answer="", stored=False, took_ms=0)
            return

        greeting = _is_greeting(message)

        # The classification call is gone. It existed to decide what to keep,
        # and keeping everything removed the decision — so all it was still
        # doing was spending a Bedrock round trip, about 0.4s and its tokens, on
        # every single message to produce a label nothing depended on.
        #
        # Bedrock prompt caching would have been the other saving, and it is not
        # available: cachePoint is rejected for every Mistral model in this
        # account (Large 3, Large 2402, Ministral 14B, Magistral). Dropping a
        # whole call beats caching one.
        retrieval = None if greeting else _pool.submit(_retrieve, message, ns)

        # Waiting for retrieval before generating cost 3.7 seconds of dead air
        # on every message, measured — and for small talk it bought nothing,
        # because the answer to "hey there" does not come from the graph. So a
        # chat turn starts writing immediately.
        #
        # A question is different: the answer IS the memory, and a fast wrong
        # answer is worse than a slow right one. Those wait.
        #
        # The retrieval still runs either way. It is what keeps the settling
        # tray honest, and its result is used when it arrives in time.
        # Every message waits for memory, and every message is kept. Deciding
        # per message was the whole problem: a plain statement of fact came back
        # from the classifier as small talk, so nothing was written — while the
        # reply said "Got it", which is the worst possible outcome. A confirmation that isn't true is worse than
        # no confirmation, and no amount of prompt tuning makes a judgement call
        # reliable enough to sit in front of "did you keep this or not".
        #
        # The cost is honest and known: about 3.7s per message for retrieval,
        # and a graph that also contains the questions, not just the answers.
        raw_context = "" if retrieval is None else retrieval.result()

        # The tray count is read before the reply so the client can caveat an
        # answer that may be missing a write still settling.
        unsettled = registry.unsettled_count(ns)
        yield conversation.sse("meta", stored=not greeting, unsettled=unsettled)

        answer_parts: list[str] = []
        try:
            for piece in conversation.stream_reply(
                message=message,
                memories=raw_context,
                history=history,
                speaker_name=user.get("name") or "",
                persona=user.get("persona") or "",
            ):
                if not answer_parts:
                    piece = conversation.strip_opener(piece)
                    if not piece:
                        continue
                answer_parts.append(piece)
                yield conversation.sse("token", text=piece)
        except Exception as exc:  # noqa: BLE001 - the person is mid-conversation
            log.exception("conversation failed for %s", ns)
            yield conversation.sse(
                "error",
                message="Lost the thread there — say that again?",
                detail=str(exc)[:200],
            )
            return

        answer = "".join(answer_parts).strip()

        # Evidence only where evidence exists. A greeting has no sources, and
        # showing an empty panel under one teaches people it means nothing.
        evidence = None
        if raw_context.strip():
            try:
                evidence = parse_context(raw_context)
            except Exception:  # noqa: BLE001 - never lose an answer over its footnote
                evidence = None

        if not greeting:
            background.add_task(_remember, ns, message)
        # A persona is answered with on every future message, so it is kept on
        # the account as well as in the graph. Written here rather than in the
        # background task because the next message may arrive before a
        # background write has finished, and being someone else for one turn is
        # exactly the inconsistency this is meant to end.
        if conversation.is_persona(message):
            try:
                auth.set_persona(user["email"], message)
            except Exception:  # noqa: BLE001 - never lose a reply over this
                log.warning("could not save persona for %s", ns)
        log.info(
            "converse ns=%s ctx=%dch stored=%s", ns, len(raw_context), "no" if greeting else "yes"
        )

        yield conversation.sse(
            "done",
            answer=answer,
            stored=not greeting,
            evidence=evidence.model_dump() if hasattr(evidence, "model_dump") else evidence,
            unsettled=unsettled,
            took_ms=int((time.monotonic() - started) * 1000),
        )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            # nginx buffers proxied responses by default, which would hold the
            # whole reply and deliver it in one piece — the exact thing this
            # endpoint exists to avoid.
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-store",
        },
    )


# Greetings are the one thing worth excluding, and they have to be recognised by
# name rather than by shape. The obvious heuristic — short, no question mark,
# nothing about the speaker — also matches "she is my lab partner", which is
# precisely the sort of sentence that must be kept. So this is a closed list of
# pleasantries: a message is a greeting only if every word in it is one of them.
#
# Greetings are skipped twice over: not stored, because "hey" is not a memory,
# and not made to wait for retrieval, because nothing in the graph answers it.
# Everything else is both kept and answered from memory.
_PLEASANTRIES = {
    "hi", "hii", "hiii", "hey", "heyy", "hello", "helo", "yo", "hola", "namaste",
    "morning", "afternoon", "evening", "night", "good", "gm", "gn", "sup",
    "thanks", "thank", "you", "thx", "ty", "cheers", "welcome",
    "ok", "okay", "k", "cool", "nice", "great", "awesome", "lovely", "perfect",
    "bye", "goodbye", "see", "later", "cya", "ttyl",
    "lol", "haha", "hehe", "hmm", "oh", "ah", "yes", "yeah", "yep", "no", "nope",
    "there", "up", "whats", "hows", "it", "going", "all", "right",
}
_WORDS = re.compile(r"[a-z']+")


def _is_greeting(message: str) -> bool:
    words = _WORDS.findall(message.lower())
    # An empty result means punctuation or emoji only, which is not a memory
    # either. A long string of pleasantries is still just a pleasantry.
    if not words:
        return True
    return all(word in _PLEASANTRIES for word in words)


def _retrieve(message: str, namespace: str) -> str:
    """Memory context for this message. Never fatal: a conversation without
    memory is a worse answer, while a failed request is no answer at all."""
    try:
        raw = reeve_gateway.context(message, namespace)
        quota.spend("context")
        return raw or ""
    except Exception as exc:  # noqa: BLE001
        log.warning("retrieval failed for %s: %s", namespace, exc)
        return ""


def _remember(namespace: str, text: str) -> None:
    """Store what the person just said, through the same tray as every other
    write so the settling caveat and the failure marking behave identically."""
    chunks = chunk_note(conversation.as_memory(text), None)
    if not chunks:
        return
    batch_id = uuid.uuid4().hex
    log.info("remembering %d chunk(s) for %s", len(chunks), namespace)
    for chunk in chunks:
        item = registry.add(
            namespace=namespace, kind="note", preview=chunk, batch_id=batch_id, store_result=None
        )
        try:
            result = reeve_gateway.store_note(chunk, namespace)
            registry.mark_written(namespace, item.id, failed=False, result=result)
            log.info("stored chunk for %s -> %s", namespace, result)
        except Exception as exc:  # noqa: BLE001
            log.warning("store failed for %s: %s", namespace, exc)
            registry.mark_written(namespace, item.id, failed=True)
