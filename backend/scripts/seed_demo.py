"""Seed the demo namespace with a term's worth of coursework.

Run this at least a day before a demo, never during one. Two reasons: writes
index asynchronously, so a namespace seeded minutes earlier is still settling;
and the ordering below is load-bearing — a fact must be indexed before the fact
that supersedes it is written, or the graph has nothing to supersede.

The corpus is deliberately ordinary. It is a student writing down what happened,
in the order it happened, including the parts that later turned out to be wrong.
That is what makes the supersession questions honest rather than staged.

Usage:
    python seed_demo.py [--photos <dir>]

Cost: no queries (writes are free), but a lot of tokens — photos especially.
"""

from __future__ import annotations

import argparse
import base64
import sys
import time
from pathlib import Path

from _probe_common import Recorder, load_env, namespace, run

load_env()

from reeve.tools import store_memory  # noqa: E402

PACE_SECONDS = 2.0
SETTLE_BETWEEN_ROUNDS = 90
MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# Round one: the term as it was first understood.
ROUND_ONE = [
    "I am taking Digital Signal Processing, Compiler Design, and Machine Learning this semester.",
    "Prof. Nair is supervising my DSP mini-project.",
    "Riya and Arjun are on my DSP project team. Riya is doing the filter design and Arjun is handling the dataset.",
    "The DSP mini-project report is due on 5 November.",
    "We decided the DSP mini-project will be a real-time noise filter for lecture recordings.",
    "The sampling rate for the DSP project is 44.1 kilohertz.",
    "Prof. Nair's office hours are Tuesday afternoons in the DSP lab.",
    "Compiler Design lab 3 is about building an SLR parse table.",
    "Dr Menon teaches Compiler Design and marks the labs herself.",
    "I read the Vaswani attention paper for the ML seminar and found the positional encoding section hard.",
    "The ML seminar presentation slot I was given is 12 November.",
    "Arjun found that our lecture recordings have a lot of low-frequency hum from the projector fan.",
    "In the 8 October lab meeting we agreed to use a notch filter for the projector hum.",
    "Riya benchmarked the notch filter and got 12 dB of hum reduction.",
    "My ML course project is on comparing tokenizer choices for Indic languages.",
    "The Compiler Design mid-semester exam is on 28 October.",
    "I borrowed the Aho compilers book from the library; it is due back on 2 November.",
    "Prof. Nair suggested I look at spectral subtraction as an alternative to notch filtering.",
]

# Round two: the corrections. Each of these replaces something above, which is
# the point of the whole demo.
ROUND_TWO = [
    "Prof. Nair moved the DSP mini-project report deadline to 19 November.",
    "We changed the DSP project sampling rate to 48 kilohertz to match the lecture hall recorder.",
    "Arjun has swapped to filter design and Riya is now handling the dataset.",
    "The ML seminar presentation slot has been moved to 26 November.",
    "After the 5 November review we dropped spectral subtraction and stayed with the notch filter.",
    "Prof. Nair's office hours have moved to Thursday mornings.",
]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photos", type=Path, help="directory of whiteboard/slide photos")
    args = parser.parse_args(argv[1:])

    ns = namespace()
    rec = Recorder("seed-demo", "Demo namespace seed")
    rec.say(f"Namespace: `{ns}`")
    rec.say("")

    if not _confirm(ns):
        print("Aborted.")
        return 1

    rec.say(f"### Round one — {len(ROUND_ONE)} memories")
    _store_all(ROUND_ONE, ns, rec)

    if args.photos:
        rec.say("")
        rec.say("### Photos")
        count = _store_photos(args.photos, ns, rec)
        if count < 4:
            rec.say("")
            rec.say(
                f"> Only {count} photo(s). The image lane declines to rank below "
                "three, so unattached photo questions will not fire. Add more "
                "before demonstrating that comparison."
            )

    rec.say("")
    rec.say(
        f"Waiting {SETTLE_BETWEEN_ROUNDS}s so round one indexes before the "
        "corrections land. A fact has to exist before it can be superseded."
    )
    time.sleep(SETTLE_BETWEEN_ROUNDS)

    rec.say("")
    rec.say(f"### Round two — {len(ROUND_TWO)} corrections")
    _store_all(ROUND_TWO, ns, rec)

    rec.say("")
    rec.say("### Next")
    rec.say("")
    rec.say(
        "Give it a few minutes, then verify with the questions in "
        "`docs/demo-script.md`. Do not seed again on the day — re-running this "
        "would create a second, competing history."
    )
    rec.save()
    return 0


def _store_all(items: list[str], ns: str, rec: Recorder) -> None:
    for index, text in enumerate(items, 1):
        store_memory(text, speaker=ns)
        rec.say(f"{index}. {text}")
        time.sleep(PACE_SECONDS)  # bursts get throttled upstream


def _store_photos(directory: Path, ns: str, rec: Recorder) -> int:
    images = sorted(p for p in directory.iterdir() if p.suffix.lower() in MEDIA_TYPES)
    for path in images:
        # Thin captions on purpose: a caption that already describes the image
        # would let text retrieval answer photo questions, which proves nothing.
        caption = f"A photo from lab work: {path.stem.replace('_', ' ')}."
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        store_memory(
            caption,
            speaker=ns,
            image_base64=encoded,
            image_media_type=MEDIA_TYPES[path.suffix.lower()],
        )
        rec.say(f"- `{path.name}` — _{caption}_")
        time.sleep(PACE_SECONDS)
    return len(images)


def _confirm(ns: str) -> bool:
    """Seeding is additive and cannot be undone selectively — only a full wipe
    of the namespace would remove it."""
    reply = input(f"Seed {len(ROUND_ONE) + len(ROUND_TWO)} memories into '{ns}'? [y/N] ")
    return reply.strip().lower() in {"y", "yes"}


if __name__ == "__main__":
    sys.exit(run(lambda: main(sys.argv)))
