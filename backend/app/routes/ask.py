"""Asking questions.

Every handler here is a plain `def` so Starlette runs it in a worker thread —
the SDK blocks, sometimes for many seconds.

One rule holds across this module: never issue two Reeve calls concurrently for
a single user action. The SDK keeps one cached client and one SSE listener
thread, and its stale-session recovery clears every outstanding response queue
when it fires — so a reconnect triggered by one call can orphan another that was
in flight. Evidence mode therefore asks, then retrieves, sequentially.
"""

from __future__ import annotations

import time

from fastapi import APIRouter

from app import quota, reeve_gateway
from app.models import Answer, AskIn, ContextOut, EntityIn, QuestionIn, TimelineIn
from app.parsers.context_parser import parse_context
from app.pending import registry

router = APIRouter()


@router.post("/api/ask", response_model=Answer)
def ask(payload: AskIn) -> Answer:
    started = time.monotonic()

    answer = reeve_gateway.ask(payload.question)
    queries = 1
    quota.spend("ask")

    evidence = None
    if payload.with_evidence:
        raw = reeve_gateway.context(payload.question)
        quota.spend("context")
        queries += 1
        evidence = parse_context(raw)

    return Answer(
        answer=answer,
        evidence=evidence,
        queries_used=queries,
        took_ms=int((time.monotonic() - started) * 1000),
        # Surfaced so the UI can caveat the answer instead of overclaiming.
        unsettled_writes=registry.unsettled_count(),
    )


@router.post("/api/context", response_model=ContextOut)
def context(payload: QuestionIn) -> ContextOut:
    raw = reeve_gateway.context(payload.question)
    quota.spend("context")
    return ContextOut(raw=raw, parsed=parse_context(raw), queries_used=1)


@router.post("/api/entity", response_model=ContextOut)
def entity(payload: EntityIn) -> ContextOut:
    """Everything the graph knows about one person, course or project.

    Deliberately built on the raw context rather than the narrated answer: the
    entity, role, relation and action edges are exactly what the narrator
    flattens into prose, and they are what the map needs.
    """
    raw = reeve_gateway.context(f"everything about {payload.name}")
    quota.spend("entity")
    return ContextOut(raw=raw, parsed=parse_context(raw), queries_used=1)


@router.post("/api/timeline", response_model=ContextOut)
def timeline(payload: TimelineIn) -> ContextOut:
    """Temporal recall. The phrasing matters — the engine parses the time phrase
    out of the question itself, so 'last week' has to survive into the query."""
    raw = reeve_gateway.context(f"What happened {payload.window}?")
    quota.spend("timeline")
    return ContextOut(raw=raw, parsed=parse_context(raw), queries_used=1)
