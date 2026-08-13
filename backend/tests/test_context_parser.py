"""Parser tests. Zero quota — everything here runs against fixed strings.

The fixtures reproduce the exact format strings from Reeve's `expand_episodes`
and `retrieve` renderers. When the hosted service changes its output, these go
red, which is the point: the alternative is a silently empty evidence panel in
the UI.
"""

from __future__ import annotations

from app.parsers.context_parser import parse_context

# Shape 3: long-term only. The common case once writes have settled.
LONG_TERM_ONLY = """Long-term memory context (Reeve; use when not contradicted by short-term memory):
[2026-08-11T09:14:02] The DSP mini-project report is due on 5 November.  (summary: The speaker recorded the DSP report deadline., emotion=neutral, importance=0.6)
  Entities: speaker, DSP mini-project
  Action: speaker recorded → deadline
  State: DSP mini-project.deadline = 5 November (superseded)

[2026-08-13T16:02:41] [event_id=42 | title=Lab meeting | year=2026] Prof. Nair moved the DSP mini-project report deadline to 19 November.  (summary: Prof. Nair moved the DSP report deadline., emotion=neutral, importance=0.75)
  Entities: Prof. Nair, DSP mini-project, speaker
  Action: Prof. Nair moved → deadline
  Relation: Nair supervises speaker
  State: DSP mini-project.deadline = 19 November
  Location: DSP Lab, Block C

Roles:
  Prof. Nair → supervisor
  speaker → student
"""

# Shape 1: a write is still in flight, so all three blocks are present.
WITH_PENDING = """Conflict rule: if short-term memory and Reeve long-term memory disagree, prefer the short-term memory fact because it is the latest information.

Short-term memory context (newest; overrides Reeve long-term memory on conflicts):
[PENDING - not yet indexed] Prof. Nair moved the deadline to 19 November.

Long-term memory context (Reeve; use when not contradicted by short-term memory):
[2026-08-11T09:14:02] The DSP mini-project report is due on 5 November.  (summary: Deadline recorded., emotion=neutral, importance=0.6)
  State: DSP mini-project.deadline = 5 November
"""

# Shape 2: nothing indexed yet, only the buffer.
PENDING_ONLY = """Short-term memory context (newest; overrides Reeve long-term memory on conflicts):
[PENDING - not yet indexed] The lab meeting decided the sampling rate is 48 kHz.
"""


def test_long_term_only_parses_two_episodes():
    parsed = parse_context(LONG_TERM_ONLY)
    assert not parsed.empty
    assert not parsed.has_conflict_rule
    assert parsed.pending == []
    assert len(parsed.episodes) == 2


def test_superseded_marker_is_the_thing_we_cannot_get_wrong():
    parsed = parse_context(LONG_TERM_ONLY)
    superseded = parsed.superseded_states
    active = parsed.active_states

    assert len(superseded) == 1
    assert superseded[0].value == "5 November"
    assert superseded[0].attribute == "deadline"

    assert len(active) == 1
    assert active[0].value == "19 November"
    # The value must not absorb the marker text.
    assert "superseded" not in active[0].value


def test_episode_head_splits_display_from_trailer():
    ep = parse_context(LONG_TERM_ONLY).episodes[0]
    assert ep.timestamp == "2026-08-11T09:14:02"
    assert ep.display == "The DSP mini-project report is due on 5 November."
    assert ep.summary == "The speaker recorded the DSP report deadline."
    assert ep.emotion == "neutral"
    assert ep.importance == 0.6


def test_event_metadata_is_extracted_not_left_in_the_display():
    ep = parse_context(LONG_TERM_ONLY).episodes[1]
    assert ep.metadata == {"event_id": "42", "title": "Lab meeting", "year": "2026"}
    assert ep.display.startswith("Prof. Nair moved")
    assert "event_id" not in ep.display


def test_graph_children_attach_to_the_right_episode():
    episodes = parse_context(LONG_TERM_ONLY).episodes
    assert episodes[0].entities == ["speaker", "DSP mini-project"]
    assert episodes[1].actions[0].actor == "Prof. Nair"
    assert episodes[1].actions[0].object == "deadline"
    assert episodes[1].relations[0].subject == "Nair"
    assert episodes[1].relations[0].object == "speaker"
    assert episodes[1].locations == ["DSP Lab", "Block C"]


def test_roles_block_is_whole_response_not_per_episode():
    parsed = parse_context(LONG_TERM_ONLY)
    assert parsed.roles == {"Prof. Nair": "supervisor", "speaker": "student"}


def test_all_three_blocks():
    parsed = parse_context(WITH_PENDING)
    assert parsed.has_conflict_rule
    assert parsed.pending == ["Prof. Nair moved the deadline to 19 November."]
    assert len(parsed.episodes) == 1


def test_pending_only_is_not_empty():
    """A write in flight with nothing indexed is a real answer, not a miss."""
    parsed = parse_context(PENDING_ONLY)
    assert not parsed.empty
    assert parsed.episodes == []
    assert len(parsed.pending) == 1


def test_empty_string_is_a_legitimate_response():
    parsed = parse_context("")
    assert parsed.empty
    assert parsed.raw == ""


def test_unrecognised_lines_are_preserved_never_dropped():
    """Tolerance contract: a format change must degrade display, not lose evidence."""
    raw = LONG_TERM_ONLY.replace(
        "  Entities: speaker, DSP mini-project",
        "  Sentiment: cautiously optimistic",
    )
    parsed = parse_context(raw)
    everything = " ".join(parsed.raw_extra + [x for ep in parsed.episodes for x in ep.raw_extra])
    assert "cautiously optimistic" in everything
    assert parsed.raw == raw


def test_garbage_does_not_raise():
    for junk in ["[[[", "State: = =", "Roles:\n  no arrow here", "\n\n\n", "[ts] x  (summary: )"]:
        parse_context(junk)
