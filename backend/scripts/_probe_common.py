"""Shared setup for the Phase 0 probes.

These scripts run BEFORE any app code exists. Their whole job is to find out
what the hosted service actually does, so the app is built against measured
behaviour rather than against the documentation. Every probe writes its raw
output into docs/experiments/ — that output is simultaneously the report's
primary data and the parser's test fixtures.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
EXPERIMENTS = REPO / "docs" / "experiments"

# Scripts run from scripts/, so the backend package root has to be importable
# before they can share the app's error classification.
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def load_env() -> None:
    """Load backend/.env without a dependency, and fail loudly if the key is absent.

    reeve/tools.py snapshots REEVE_API_KEY at import time, so this must run
    before `import reeve` anywhere in the process.
    """
    env_path = BACKEND / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

    if not os.environ.get("REEVE_API_KEY"):
        sys.exit("REEVE_API_KEY is not set. Copy .env.example to backend/.env and fill it in.")


def namespace() -> str:
    return os.environ.get("CARREL_NAMESPACE", "carrel-probe")


class Recorder:
    """Accumulates a markdown transcript and writes it to docs/experiments/."""

    def __init__(self, name: str, title: str):
        self.name = name
        self.started = datetime.now(timezone.utc)
        self.lines = [
            f"# {title}",
            "",
            f"Run: `{self.started.isoformat(timespec='seconds')}`",
            "",
        ]

    def say(self, text: str = "") -> None:
        print(text)
        self.lines.append(text)

    def block(self, label: str, body: str) -> None:
        """Record a verbatim response. Never summarise — the raw string is the evidence."""
        print(f"\n--- {label} ---\n{body}\n")
        self.lines += [f"**{label}**", "", "```", body.rstrip(), "```", ""]

    def save(self) -> Path:
        EXPERIMENTS.mkdir(parents=True, exist_ok=True)
        path = EXPERIMENTS / f"{self.name}.md"
        path.write_text("\n".join(self.lines) + "\n")
        print(f"\nsaved -> {path.relative_to(REPO)}")
        return path


def token() -> str:
    """A token unlikely to collide with anything already in the namespace."""
    return f"CARREL{int(time.time())}"


def run(main) -> int:
    """Run a probe's main(), turning SDK failures into an actionable message.

    `make check` is usually the first thing anyone runs on a fresh clone, and a
    stack trace is a poor answer when the real problem is an unset key or an
    exhausted quota. This reuses the application's own error table so the CLI
    and the web UI never disagree about what went wrong.
    """
    from app.errors import classify  # imported late: needs .env loaded first

    try:
        return main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as exc:  # noqa: BLE001 - the whole point is to classify it
        error = classify(exc)
        print(f"\n{error.user_message}", file=sys.stderr)
        if error.code == "reeve_auth":
            print(
                f"  Set a working key in {BACKEND / '.env'} and try again.",
                file=sys.stderr,
            )
        if error.detail:
            print(f"  ({error.detail})", file=sys.stderr)
        return 1
