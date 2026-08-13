"""Phase 0 probe: what is actually switched on right now?

Vision, photo retention and async writes are operator-controlled on the Reeve
side. If one is off, this application does not get an error — answers simply
stop being grounded in the image, quietly. So every results page records the
capability state at the moment it was measured, and this is what produces it.

Free: memory_config does not count against the query quota.
"""

from __future__ import annotations

import sys

from _probe_common import Recorder, load_env, namespace, run

load_env()

import reeve  # noqa: E402
from reeve.tools import memory_config  # noqa: E402

# Below this, the SDK lacks the idle-session reconnect (0.1.40) and the
# attached-photo query arguments (0.1.41) this project depends on.
MINIMUM_SDK = (0, 1, 41)


def main() -> int:
    rec = Recorder("probe-config", "Probe: live service capabilities")

    version = getattr(reeve, "__version__", "unknown")
    rec.say(f"SDK version: `{version}` · namespace `{namespace()}`")

    if _parse(version) < MINIMUM_SDK:
        rec.say("")
        rec.say(
            f"> **Too old.** This project needs >= "
            f"{'.'.join(str(n) for n in MINIMUM_SDK)}: below it there is no "
            "reconnection when an idle session expires, and no way to attach a "
            "photo to a question."
        )

    config = memory_config()
    rec.say("")
    rec.say("| Setting | Value |")
    rec.say("|---|---|")
    for key in sorted(config):
        rec.say(f"| {key} | {config[key]} |")

    rec.say("")
    rec.say("### What this project needs")
    rec.say("")
    required = [
        ("vision_enabled", "photo questions at all"),
        ("image_retention_enabled", "re-reading a photo later — the whole pillar"),
        ("multimodal_image_search_enabled", "finding a photo by how it looks"),
        ("async_write_enabled", "the settling tray has something to show"),
    ]
    for key, why in required:
        value = config.get(key)
        state = "on" if value else "OFF"
        rec.say(f"- **{key}: {state}** — needed for {why}")

    missing = [key for key, _ in required if not config.get(key)]
    rec.say("")
    if missing:
        rec.say(
            f"> {len(missing)} capability/capabilities are off. Features depending "
            "on them will degrade silently rather than erroring, which is exactly "
            "why the app shows capability badges."
        )
    else:
        rec.say("Everything this project relies on is live.")

    rec.save()
    return 0


def _parse(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in version.split(".")[:3])
    except ValueError:
        return (0, 0, 0)


if __name__ == "__main__":
    sys.exit(run(main))
