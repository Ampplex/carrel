"""Split long notes before storing them.

A documented limit of the retrieval engine: one fact buried inside a long
brain-dump dilutes its own embedding, and can lose to shorter, less relevant
memories. A four-kilobyte page of lecture notes containing one crucial decision
is exactly the shape that fails.

Reeve does not chunk for you, so it is the application's job. Splitting on
paragraph boundaries first and sentences second keeps each chunk a coherent
thought, and prefixing every chunk with a shared context line means a fragment
retrieved on its own still says what it belongs to.
"""

from __future__ import annotations

import re

from app.config import settings

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def chunk_note(text: str, context_line: str = "") -> list[str]:
    """Split `text` into storable chunks. Short notes pass through untouched."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= settings.chunk_threshold_chars:
        return [text]

    chunks: list[str] = []
    for paragraph in (p.strip() for p in text.split("\n\n") if p.strip()):
        if len(paragraph) <= settings.chunk_target_chars:
            chunks.append(paragraph)
            continue
        chunks.extend(_split_sentences(paragraph))

    prefix = f"{context_line.strip()} — " if context_line.strip() else ""
    return [f"{prefix}{chunk}" for chunk in chunks[: settings.max_chunks]]


def _split_sentences(paragraph: str) -> list[str]:
    """Pack sentences up to the target size, never breaking mid-sentence."""
    out: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(paragraph):
        if not sentence:
            continue
        if current and len(current) + len(sentence) + 1 > settings.chunk_target_chars:
            out.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current.strip():
        out.append(current.strip())
    return out


def would_exceed_limit(text: str) -> bool:
    """True if the note would need more chunks than we are willing to store."""
    return len(chunk_note(text)) >= settings.max_chunks and len(text) > settings.chunk_threshold_chars
