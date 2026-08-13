"""Request and response shapes for the HTTP API.

Note what is absent: no endpoint accepts a `speaker` or `namespace`. That is
owned by the server (see `reeve_gateway`), because a namespace partitions data
but does not secure it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.parsers.context_parser import ParsedContext
from app.pending import PendingWrite


class NoteIn(BaseModel):
    text: str = Field(min_length=1)
    # Prefixed onto every chunk of a long note so a fragment retrieved alone
    # still says what it belongs to.
    context_line: str = ""


class AskIn(BaseModel):
    question: str = Field(min_length=1)
    # Evidence mode calls retrieve_memory_context as well, costing a second
    # query. The UI prints that cost on the button.
    with_evidence: bool = False


class QuestionIn(BaseModel):
    question: str = Field(min_length=1)


class EntityIn(BaseModel):
    name: str = Field(min_length=1)


class TimelineIn(BaseModel):
    window: str = "last week"


class SearchIn(BaseModel):
    query: str = Field(min_length=1)


class PhotoAskIn(BaseModel):
    question: str = Field(min_length=1)
    photo_id: str


class ResetIn(BaseModel):
    confirm: str


class WriteAccepted(BaseModel):
    batch_id: str
    pending: list[PendingWrite]
    chunked: bool = False
    eta_seconds: int = 60


class PhotoAccepted(WriteAccepted):
    photo_id: str
    thumb_url: str


class Answer(BaseModel):
    answer: str
    evidence: ParsedContext | None = None
    queries_used: int
    took_ms: int
    # How many writes might still be missing from this answer. The UI turns a
    # non-zero value into a visible caveat rather than hiding it.
    unsettled_writes: int = 0


class PhotoAnswer(BaseModel):
    answer: str
    mode: str
    note: str
    queries_used: int
    took_ms: int


class ContextOut(BaseModel):
    raw: str
    parsed: ParsedContext
    queries_used: int


class PhotoOut(BaseModel):
    photo_id: str
    caption: str
    thumb_url: str
    stored_at: float
