"""Phase 0 probe: how long until a stored fact is actually answerable?

This settles a documented ambiguity that decides how the UI must behave.

The server merges a short-term buffer of not-yet-indexed writes into the
retrieval context under a "prefer short-term on conflict" header, which implies
a fact is answerable the instant it is stored. But that buffer is a per-process
in-memory dict, so if the hosted service runs more than one worker, whether you
see your own pending write depends on which worker your session landed on.

Either answer is fine — the UI is designed to be honest both ways — but we need
to know which one we are building against, and we need a real median settle time
for the report.

Cost: ~14 queries per run.
"""

from __future__ import annotations

import sys
import time

from _probe_common import Recorder, load_env, namespace, token

load_env()

from reeve.tools import query_memory, retrieve_memory_context, store_memory  # noqa: E402

# Probe at these offsets (seconds after the store returns).
CHECKPOINTS = [0, 10, 20, 40, 60, 90]

# query_memory costs the same as retrieve_memory_context but hides the PENDING
# marker, so we only spend it where the difference is interesting.
NARRATE_AT = {0, 60}


def main() -> int:
    ns = namespace()
    tok = token()
    fact = (
        f"The {tok} lab meeting decided the sampling rate for the DSP mini-project "
        f"is 48 kilohertz."
    )
    question = f"What sampling rate did the {tok} lab meeting decide on?"

    rec = Recorder("probe-readafterwrite", "Probe: read-after-write latency")
    rec.say(f"Namespace: `{ns}`")
    rec.say(f"Token: `{tok}`")
    rec.say("")
    rec.say(f"Stored fact: {fact}")
    rec.say(f"Question: {question}")
    rec.say("")

    wrote = store_memory(fact, speaker=ns)
    t0 = time.monotonic()
    rec.block("store_memory returned", repr(wrote))

    rec.say("| t (s) | token in context | under PENDING | indexed episode | narrated answer |")
    rec.say("|---|---|---|---|---|")

    for target in CHECKPOINTS:
        while (elapsed := time.monotonic() - t0) < target:
            time.sleep(min(1.0, target - elapsed))

        ctx = retrieve_memory_context(question, speaker=ns)
        present = tok in ctx
        # The pending block is rendered with this literal marker on each line.
        pending = "[PENDING - not yet indexed]" in ctx and present
        # If the token shows up outside the pending block, it is really indexed.
        indexed = present and not _only_in_pending(ctx, tok)

        answer = ""
        if target in NARRATE_AT:
            answer = query_memory(question, speaker=ns).strip().replace("\n", " ")
            answer = (answer[:60] + "…") if len(answer) > 60 else answer

        actual = int(time.monotonic() - t0)
        rec.say(
            f"| {actual} | {_tick(present)} | {_tick(pending)} | {_tick(indexed)} | "
            f"{answer or '—'} |"
        )

        if target == CHECKPOINTS[-1] or (indexed and target >= 20):
            rec.block(f"full context at t={actual}s", ctx)
            if indexed:
                break

    rec.say("")
    rec.say(
        "Interpretation: if the token appears at t=0 under PENDING, the app may "
        "tell the user their write is already answerable. If it only appears once "
        "the episode is indexed, the UI must never imply otherwise."
    )
    rec.save()
    return 0


def _only_in_pending(ctx: str, tok: str) -> bool:
    """True if every line mentioning the token is inside the short-term block."""
    long_term_marker = "Long-term memory context"
    if long_term_marker not in ctx:
        return True
    _, _, long_term = ctx.partition(long_term_marker)
    return tok not in long_term


def _tick(value: bool) -> str:
    return "yes" if value else "no"


if __name__ == "__main__":
    sys.exit(main())
