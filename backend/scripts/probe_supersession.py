"""Phase 0 probe: does the store really know which fact replaced which?

This is the project's central claim, so it gets measured rather than asserted.
The test is deliberately the hard version: not "does it return the new date"
(a vector store might, by luck of phrasing) but "does it return the new date AND
still know the old one, AND label which is which".

The evidence is the literal ` (superseded)` suffix in the raw retrieval context.
That string is produced by Reeve, not by this application, which is what makes
it worth putting on screen in a viva.

Cost: ~6 queries per run, plus waiting for two writes to index.
"""

from __future__ import annotations

import sys
import time

from _probe_common import Recorder, load_env, namespace, run, token

load_env()

from reeve.tools import query_memory, retrieve_memory_context, store_memory  # noqa: E402

SETTLE_SECONDS = 75
SUPERSEDED_MARKER = "(superseded)"


def main() -> int:
    ns = namespace()
    tok = token()

    original = f"The {tok} mini-project report is due on 5 November."
    revision = f"Prof. Nair moved the {tok} mini-project report deadline to 19 November."
    now_q = f"When is the {tok} report due?"
    then_q = f"When was the {tok} report originally due?"

    rec = Recorder("probe-supersession", "Probe: state supersession")
    rec.say(f"Namespace: `{ns}` · token `{tok}`")
    rec.say("")
    rec.say("The claim under test: after a fact is replaced, the store can answer")
    rec.say("both the present-tense and the historical question, and can say which")
    rec.say("value is current. A nearest-neighbour index cannot — it holds two")
    rec.say("equally plausible sentences with no relation between them.")
    rec.say("")

    rec.say(f"1. Storing: {original}")
    store_memory(original, speaker=ns)
    _wait("first write", rec)

    rec.block("context before the revision", retrieve_memory_context(now_q, speaker=ns))

    rec.say(f"2. Storing the contradiction: {revision}")
    store_memory(revision, speaker=ns)
    _wait("second write", rec)

    answer_now = query_memory(now_q, speaker=ns).strip()
    answer_then = query_memory(then_q, speaker=ns).strip()
    context = retrieve_memory_context(now_q, speaker=ns)

    rec.say("")
    rec.say("| Question | Answer |")
    rec.say("|---|---|")
    rec.say(f"| {now_q} | {answer_now} |")
    rec.say(f"| {then_q} | {answer_then} |")
    rec.say("")

    rec.block("raw context after the revision", context)

    superseded_lines = [
        line.strip()
        for line in context.splitlines()
        if SUPERSEDED_MARKER in line
    ]

    rec.say("### Verdict")
    rec.say("")
    checks = [
        ("current answer names 19 November", "19 November" in answer_now),
        ("current answer does NOT name 5 November", "5 November" not in answer_now),
        ("historical answer names 5 November", "5 November" in answer_then),
        (f"context carries a literal `{SUPERSEDED_MARKER}` line", bool(superseded_lines)),
    ]
    for label, passed in checks:
        rec.say(f"- {'PASS' if passed else 'FAIL'} — {label}")

    if superseded_lines:
        rec.say("")
        rec.say("The line that proves it, verbatim from Reeve:")
        rec.say("")
        for line in superseded_lines:
            rec.say(f"    {line}")

    rec.say("")
    if all(passed for _, passed in checks):
        rec.say("All four hold: supersession works end to end through the hosted path.")
    else:
        rec.say(
            "At least one check failed. Note that the narrated answers are "
            "model-dependent and the retrieval layer is the one that owns this "
            "property — a FAIL on an answer check with a PASS on the context "
            "check means the engine is right and the phrasing is off."
        )

    rec.save()
    return 0


def _wait(label: str, rec: Recorder) -> None:
    """Writes index asynchronously; polling beats a fixed sleep but the buffer
    makes a naive poll ambiguous, so this simply waits out the window."""
    rec.say(f"   waiting {SETTLE_SECONDS}s for the {label} to index…")
    time.sleep(SETTLE_SECONDS)


if __name__ == "__main__":
    sys.exit(run(main))
