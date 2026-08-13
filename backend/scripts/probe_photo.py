"""Phase 0 probe: can a stored photo answer a question nobody anticipated?

This is the riskiest assumption in the project, which is why it is probed on day
one. If the answer is no, the photo pillar has to be rethought before any UI is
built around it.

The test design matters. It is not enough to ask something the caption already
covers — that proves only that text retrieval works. The question has to concern
a detail that exists in the image and NOT in the caption, so the only way to
answer it is to look at the picture again.

Both routes are measured:
  attached   — the image goes with the question (deterministic vision path)
  unattached — the photo must be selected by the image lane on its own merits

Usage:
    python probe_photo.py <image-dir> ["question about a detail"] ...

Store at least four images: the image lane declines to rank at all below three,
so an unattached miss with two photos tells you nothing.

Cost: ~2 queries per question, plus one store per photo.
"""

from __future__ import annotations

import base64
import sys
import time
from pathlib import Path

from _probe_common import Recorder, load_env, namespace, run, token

load_env()

from reeve.tools import _get_client, query_memory, search_image_memories, store_memory  # noqa: E402

SETTLE_SECONDS = 90
IMAGE_LANE_MIN_SAMPLE = 3
MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    image_dir = Path(argv[1]).expanduser()
    questions = argv[2:] or [
        "What text is visible in the top-right of the photo?",
        "How many separate diagrams are drawn?",
        "What colour is the writing?",
    ]

    images = sorted(
        p for p in image_dir.iterdir() if p.suffix.lower() in MEDIA_TYPES
    )
    if not images:
        print(f"No usable images in {image_dir}")
        return 2

    ns = namespace()
    tok = token()
    rec = Recorder("probe-photo", "Probe: photo re-interrogation")
    rec.say(f"Namespace: `{ns}` · token `{tok}`")
    rec.say(f"Images: {len(images)} from `{image_dir}`")
    rec.say("")

    if len(images) < IMAGE_LANE_MIN_SAMPLE + 1:
        rec.say(
            f"> Warning: only {len(images)} images. The image lane stays silent "
            f"below {IMAGE_LANE_MIN_SAMPLE}, so unattached results here are not "
            "evidence of anything."
        )
        rec.say("")

    # Captions are deliberately thin. A rich caption would let text retrieval
    # answer the questions and prove nothing about the image.
    stored: list[tuple[Path, str]] = []
    for path in images:
        media_type = MEDIA_TYPES[path.suffix.lower()]
        caption = f"A {tok} photo taken during lab work."
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        store_memory(
            caption, speaker=ns, image_base64=encoded, image_media_type=media_type
        )
        stored.append((path, encoded))
        rec.say(f"- stored `{path.name}` with the caption: _{caption}_")
        time.sleep(2)  # pace: vision extraction is heavy and bursts get throttled

    rec.say("")
    rec.say(f"Waiting {SETTLE_SECONDS}s for vision processing and indexing…")
    time.sleep(SETTLE_SECONDS)

    first_path, first_b64 = stored[0]
    media_type = MEDIA_TYPES[first_path.suffix.lower()]

    rec.say("")
    rec.say("| Question | Attached | Unattached |")
    rec.say("|---|---|---|")

    for question in questions:
        attached = _ask_attached(question, ns, first_b64, media_type)
        time.sleep(2)
        unattached = query_memory(question, speaker=ns).strip().replace("\n", " ")
        time.sleep(2)
        rec.say(f"| {question} | {_trim(attached)} | {_trim(unattached)} |")

    rec.say("")
    rec.block(
        "text-to-image search",
        search_image_memories(query="whiteboard or lab photo", speaker=ns),
    )

    rec.say("### How to read this")
    rec.say("")
    rec.say(
        "The attached column is the capability claim: if it names a detail that "
        "the caption never mentioned, the original image was genuinely re-read at "
        "query time. Mark each row correct or incorrect by eye — only you can see "
        "the photographs — and carry the tally into `docs/results.md`."
    )
    rec.say("")
    rec.say(
        "If the attached column also fails, the photo pillar does not work "
        "through the hosted path and the product needs rethinking. That is the "
        "outcome this probe exists to find early."
    )
    rec.save()
    return 0


def _ask_attached(question: str, ns: str, image_b64: str, media_type: str) -> str:
    """The SDK's query_memory takes image_path/image_url but not image_base64,
    so reach the tool directly rather than writing a temp file."""
    result = _get_client().call_tool(
        "query_memory",
        {
            "question": question,
            "speaker": ns,
            "image_base64": image_b64,
            "image_media_type": media_type,
        },
    )
    return str(result).strip().replace("\n", " ")


def _trim(text: str, limit: int = 90) -> str:
    return (text[:limit] + "…") if len(text) > limit else text


if __name__ == "__main__":
    sys.exit(run(lambda: main(sys.argv)))
