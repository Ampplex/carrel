"""One endpoint for talking to Carrel.

`POST /api/converse` replaces the old split between "ask" and "store": the
client sends whatever the person typed and gets back a stream of server-sent
events. Deciding what the message *was* now happens here, with a model, rather
than in the app with a regex over question marks.

The order of work is the part worth reading.

    retrieve  ──► always, for every message, before anything is generated
    classify  ──► concurrently, because it needs no memory
    stream    ──► the reply, in pieces, as it is written
    store     ──► after the reply, in the background, if it was worth keeping

Retrieval and classification overlap because they touch different services;
they are joined before generation because generation needs both. Storing waits
until the reply has been streamed, so a slow write never delays a word of it —
and it goes through the same pending registry as every other write, so the
"still settling" caveat keeps working exactly as before.

There is one rule inherited from the rest of this codebase and it still holds:
never two Reeve calls at once for a single user action. Retrieval runs alone;
the store that may follow runs after the response is finished.
"""

from __future__ import annotations

import logging
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

        # Both of these are network calls to different places, so they overlap.
        retrieval = _pool.submit(_retrieve, message, ns)
        intent_future = _pool.submit(conversation.classify, message)

        raw_context = retrieval.result()
        intent = intent_future.result()

        # The tray count is read before the reply so the client can caveat an
        # answer that may be missing a write still settling.
        unsettled = registry.unsettled_count(ns)
        yield conversation.sse("meta", intent=intent, unsettled=unsettled)

        answer_parts: list[str] = []
        try:
            for piece in conversation.stream_reply(
                message=message, memories=raw_context, history=history
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
        if intent == "ask" and raw_context.strip():
            try:
                evidence = parse_context(raw_context)
            except Exception:  # noqa: BLE001 - never lose an answer over its footnote
                evidence = None

        if intent == "remember":
            background.add_task(_remember, ns, message)

        yield conversation.sse(
            "done",
            answer=answer,
            stored=intent == "remember",
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
    chunks = chunk_note(text, None)
    if not chunks:
        return
    batch_id = uuid.uuid4().hex
    for chunk in chunks:
        item = registry.add(
            namespace=namespace, kind="note", preview=chunk, batch_id=batch_id, store_result=None
        )
        try:
            result = reeve_gateway.store_note(chunk, namespace)
            registry.mark_written(namespace, item.id, failed=False, result=result)
        except Exception as exc:  # noqa: BLE001
            log.warning("store failed for %s: %s", namespace, exc)
            registry.mark_written(namespace, item.id, failed=True)
