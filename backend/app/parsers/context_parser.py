"""Parse the text that `retrieve_memory_context` returns into typed blocks.

This is the most important module in the backend, and the most fragile. Reeve's
narrated answer (`query_memory`) is prose — good for reading, useless for
building a UI on. The raw context is the only structured surface the SDK
exposes, and it is the layer that owns retrieval truth: it carries the
`(superseded)` markers, the pending-write block and the graph edges that the
narrator flattens away.

It is also an internal rendering, not a published contract. It is produced by
`expand_episodes` / `retrieve` in the Reeve server and could change between
releases without notice. Two consequences shape this module:

  1. Parsing is TOLERANT. Anything unrecognised is preserved in `raw_extra`
     rather than dropped, and the caller always keeps the original string so the
     UI can offer a raw toggle. A parser miss must degrade the display, never
     lose the evidence.
  2. The tests run against fixtures captured from the live service, so a change
     in the upstream format shows up as a red test rather than as a silently
     empty panel.

Grammar, from the server's own renderer:

    Conflict rule: ...                                    (only when both blocks present)

    Short-term memory context (newest; ...):              (only when writes are in flight)
    [PENDING - not yet indexed] <raw text>

    Long-term memory context (Reeve; ...):                (only when something matched)
    [<ts>] [event_id=.. | title=.. | year=.. | phase=..] <display>  (summary: .., emotion=.., importance=..)
      Entities: a, b
      Action: <actor> <verb> -> <object>
      Relation: <subject> <relation> <object>
      State: <entity>.<attr> = <value>[ (superseded)]
      Location: <rendered place>

    Roles:                                                (trailing, whole-response)
      <entity> -> <role>

All three top blocks are optional; an empty string is a legitimate response
meaning "nothing matched".
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

CONFLICT_RULE_PREFIX = "Conflict rule:"
SHORT_TERM_HEADER = "Short-term memory context"
LONG_TERM_HEADER = "Long-term memory context"
PENDING_MARKER = "[PENDING - not yet indexed]"
ROLES_HEADER = "Roles:"

# `[<ts>]<optional metadata> <display>` — metadata is a second bracketed group
# only when the episode belongs to a multi-line event.
_EPISODE_HEAD = re.compile(r"^\[(?P<ts>[^\]]*)\](?P<rest>.*)$")
_METADATA = re.compile(r"^\s*\[(?P<meta>[^\]]*=[^\]]*)\]\s*(?P<display>.*)$")

# The trailing annotation is appended by the renderer, so it is anchored at the
# end and parsed right-to-left: a summary may itself contain ", emotion" text,
# but the real one is always last.
_TRAILER = re.compile(
    r"\s*\(summary:\s*(?P<summary>.*),\s*emotion=(?P<emotion>[^,]*),"
    r"\s*importance=(?P<importance>[^)]*)\)\s*$",
    re.DOTALL,
)

_STATE = re.compile(
    r"^(?P<entity>.+?)\.(?P<attr>[^.=]+?)\s*=\s*(?P<value>.*?)(?P<superseded>\s*\(superseded\))?$"
)


class StateFact(BaseModel):
    """A `State:` line. `superseded` is the whole point of this parser."""

    entity: str
    attribute: str
    value: str
    superseded: bool = False


class ActionFact(BaseModel):
    actor: str
    verb: str
    object: str | None = None


class RelationFact(BaseModel):
    subject: str
    relation: str
    object: str


class Episode(BaseModel):
    timestamp: str
    display: str
    summary: str | None = None
    emotion: str | None = None
    importance: float | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    entities: list[str] = Field(default_factory=list)
    actions: list[ActionFact] = Field(default_factory=list)
    relations: list[RelationFact] = Field(default_factory=list)
    states: list[StateFact] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    raw_extra: list[str] = Field(default_factory=list)


class ParsedContext(BaseModel):
    """Everything the UI needs, plus the untouched original."""

    raw: str
    empty: bool = False
    has_conflict_rule: bool = False
    pending: list[str] = Field(default_factory=list)
    episodes: list[Episode] = Field(default_factory=list)
    roles: dict[str, str] = Field(default_factory=dict)
    raw_extra: list[str] = Field(default_factory=list)

    @property
    def superseded_states(self) -> list[StateFact]:
        return [s for ep in self.episodes for s in ep.states if s.superseded]

    @property
    def active_states(self) -> list[StateFact]:
        return [s for ep in self.episodes for s in ep.states if not s.superseded]


def parse_context(raw: str) -> ParsedContext:
    """Parse a `retrieve_memory_context` response. Never raises on bad input."""
    if not raw or not raw.strip():
        return ParsedContext(raw=raw or "", empty=True)

    result = ParsedContext(raw=raw)
    section = "preamble"
    current: Episode | None = None
    in_roles = False

    for line in raw.splitlines():
        stripped = line.strip()

        if not stripped:
            continue

        # ── Section headers ────────────────────────────────────────────────
        if stripped.startswith(CONFLICT_RULE_PREFIX):
            result.has_conflict_rule = True
            continue
        if stripped.startswith(SHORT_TERM_HEADER):
            section, in_roles = "short_term", False
            continue
        if stripped.startswith(LONG_TERM_HEADER):
            section, in_roles = "long_term", False
            continue
        if stripped == ROLES_HEADER:
            in_roles = True
            current = None
            continue

        # ── Trailing roles block ───────────────────────────────────────────
        if in_roles:
            entity, arrow, role = stripped.partition("→")
            if arrow:
                result.roles[entity.strip()] = role.strip()
            else:
                result.raw_extra.append(line)
            continue

        # ── Pending writes ─────────────────────────────────────────────────
        if stripped.startswith(PENDING_MARKER):
            result.pending.append(stripped[len(PENDING_MARKER) :].strip())
            continue
        if section == "short_term":
            # Inside the short-term block but without the marker: keep it, do
            # not guess.
            result.raw_extra.append(line)
            continue

        # ── Episode children (indented two spaces by the renderer) ─────────
        if current is not None and line.startswith("  ") and _is_child(stripped):
            _attach_child(current, stripped)
            continue

        # ── Episode head ───────────────────────────────────────────────────
        head = _EPISODE_HEAD.match(stripped)
        if head:
            current = _parse_episode_head(head)
            result.episodes.append(current)
            continue

        # Unrecognised. Preserve rather than drop.
        if current is not None:
            current.raw_extra.append(line)
        else:
            result.raw_extra.append(line)

    result.empty = not (result.episodes or result.pending)
    return result


_CHILD_PREFIXES = ("Entities:", "Action:", "Relation:", "State:", "Location:")


def _is_child(stripped: str) -> bool:
    return stripped.startswith(_CHILD_PREFIXES)


def _parse_episode_head(head: re.Match[str]) -> Episode:
    rest = head.group("rest")
    metadata: dict[str, str] = {}

    meta_match = _METADATA.match(rest)
    if meta_match:
        for pair in meta_match.group("meta").split("|"):
            key, _, value = pair.partition("=")
            if value:
                metadata[key.strip()] = value.strip()
        rest = meta_match.group("display")

    display = rest.strip()
    summary = emotion = None
    importance = None

    trailer = _TRAILER.search(display)
    if trailer:
        display = display[: trailer.start()].strip()
        summary = trailer.group("summary").strip()
        emotion = trailer.group("emotion").strip()
        try:
            importance = float(trailer.group("importance").strip())
        except ValueError:
            importance = None

    return Episode(
        timestamp=head.group("ts"),
        display=display,
        summary=summary,
        emotion=emotion,
        importance=importance,
        metadata=metadata,
    )


def _split_actor_verb(text: str, known_entities: list[str]) -> tuple[str, str]:
    """Split `Prof. Nair moved` into actor and verb.

    The renderer joins actor and verb with a bare space, so the boundary is
    genuinely ambiguous for multi-word actors. The episode's `Entities:` line is
    emitted before its actions, so by now we know the real names — match the
    longest one that the text starts with, and only fall back to splitting on
    the first space when no entity fits.
    """
    for entity in sorted(known_entities, key=len, reverse=True):
        if entity and text.startswith(entity):
            remainder = text[len(entity) :].strip()
            if remainder:
                return entity, remainder

    actor, _, verb = text.partition(" ")
    return actor.strip(), verb.strip()


def _attach_child(episode: Episode, stripped: str) -> None:
    label, _, body = stripped.partition(":")
    body = body.strip()

    if label == "Entities":
        episode.entities.extend(e.strip() for e in body.split(",") if e.strip())

    elif label == "Action":
        actor_verb, arrow, obj = body.partition("→")
        actor, verb = _split_actor_verb(actor_verb.strip(), episode.entities)
        episode.actions.append(
            ActionFact(
                actor=actor,
                verb=verb,
                object=obj.strip() if arrow else None,
            )
        )

    elif label == "Relation":
        # `<subject> <relation> <object>` with no delimiters. Three words is the
        # common shape; anything longer is ambiguous, so assume a single-word
        # relation in the middle and keep the original if that fails.
        parts = body.split()
        if len(parts) >= 3:
            episode.relations.append(
                RelationFact(subject=parts[0], relation=parts[1], object=" ".join(parts[2:]))
            )
        else:
            episode.raw_extra.append(stripped)

    elif label == "State":
        match = _STATE.match(body)
        if match:
            episode.states.append(
                StateFact(
                    entity=match.group("entity").strip(),
                    attribute=match.group("attr").strip(),
                    value=match.group("value").strip(),
                    superseded=bool(match.group("superseded")),
                )
            )
        else:
            episode.raw_extra.append(stripped)

    elif label == "Location":
        episode.locations.extend(loc.strip() for loc in body.split(",") if loc.strip())

    else:
        episode.raw_extra.append(stripped)
