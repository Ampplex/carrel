"""Chunking tests. Zero quota.

Long notes dilute their own key fact in retrieval — a page of lecture notes with
one crucial decision in it can lose to a shorter, less relevant memory. Reeve
does not chunk, so the app must, and the contract is: never split mid-sentence,
never drop text, and keep each piece able to say what it belongs to.
"""

from __future__ import annotations

from app.chunking import chunk_note
from app.config import settings


def test_short_notes_pass_through_untouched():
    """Most captures are one or two sentences and must not be mangled."""
    text = "Prof. Nair moved the DSP report deadline to 19 November."
    assert chunk_note(text) == [text]


def test_empty_input_yields_nothing():
    assert chunk_note("") == []
    assert chunk_note("   \n  ") == []


def test_long_note_splits():
    text = " ".join(f"Sentence number {i} about the lab session." for i in range(120))
    chunks = chunk_note(text)
    assert len(chunks) > 1


def test_no_chunk_is_wildly_over_target():
    """Sentences are packed up to the target, so a chunk may exceed it slightly
    when one sentence is long — but it must not run away."""
    text = " ".join(f"Sentence number {i} about the lab session." for i in range(120))
    for chunk in chunk_note(text):
        assert len(chunk) <= settings.chunk_target_chars * 2


def test_sentences_are_never_broken_mid_way():
    text = " ".join(f"Fact {i} was recorded during the session." for i in range(90))
    for chunk in chunk_note(text):
        assert not chunk.endswith(" was")
        assert not chunk.endswith("Fact")


def test_paragraph_boundaries_are_preferred():
    first = "A" * 500
    second = "B" * 500
    third = "C" * 500
    chunks = chunk_note(f"{first}\n\n{second}\n\n{third}")
    assert len(chunks) == 3
    assert chunks[0].startswith("A")
    assert chunks[1].startswith("B")


def test_context_line_is_prefixed_so_a_fragment_still_says_what_it_is():
    """A chunk retrieved on its own has no neighbours to explain it."""
    text = "\n\n".join("X" * 400 for _ in range(4))
    chunks = chunk_note(text, context_line="DSP lecture 7")
    assert all(chunk.startswith("DSP lecture 7 — ") for chunk in chunks)


def test_chunk_count_is_capped():
    text = "\n\n".join(f"Paragraph {i}. " + "y" * 400 for i in range(50))
    assert len(chunk_note(text)) <= settings.max_chunks


def test_no_content_is_silently_dropped_for_a_normal_note():
    """Within the cap, every sentence must survive somewhere."""
    sentences = [f"Decision {i} was taken." for i in range(40)]
    chunks = chunk_note(" ".join(sentences))
    joined = " ".join(chunks)
    for sentence in sentences:
        assert sentence in joined
