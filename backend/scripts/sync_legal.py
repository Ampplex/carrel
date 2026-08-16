"""Regenerate app/legal_content.py from the app's legal.ts.

The app's copy is canonical: it is what somebody actually reads and agrees to.
This copies it to the server so the same words can be served at a public URL —
which Google requires before an OAuth consent screen may leave Testing.

    cd backend && python scripts/sync_legal.py

Run it after editing mobile/src/legal.ts. `tests/test_legal_sync.py` fails if
you forget, which is the point: a privacy notice that says one thing in the app
and another on the web is worse than having only one of them.
"""

from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
SOURCE = ROOT / "mobile" / "src" / "legal.ts"
TARGET = ROOT / "backend" / "app" / "legal_content.py"

HEADER = '''"""The Terms and Privacy Policy, as the server publishes them.

Generated from `mobile/src/legal.ts` by `scripts/sync_legal.py` — not written by
hand. Two hand-maintained copies of a privacy notice drift, and the stale one is
always the published one. `tests/test_legal_sync.py` fails if this file falls
behind the app's copy.

The app embeds its own copy so it works offline and so the wording somebody
agreed to is the wording their build displayed. This copy exists because Google
requires a publicly reachable privacy policy URL before an OAuth consent screen
can leave Testing, and because a policy nobody outside the app can read is not
much of a policy.
"""

'''


def parse(source: str) -> dict:
    version = re.search(r'LEGAL_VERSION = "([^"]+)"', source).group(1)

    def doc(name: str) -> dict:
        block = re.search(rf"export const {name}: LegalDoc = \{{(.*?)\n\}};", source, re.S).group(1)
        updated = re.search(r'updated: "([^"]+)"', block)
        sections = [
            {
                "heading": json.loads(f'"{m.group(1)}"'),
                "body": json.loads(f'"{m.group(2)}"'),
            }
            for m in re.finditer(
                r'heading:\s*"((?:[^"\\]|\\.)*)",\s*\n\s*body:\s*\n?\s*"((?:[^"\\]|\\.)*)"', block
            )
        ]
        if not sections:
            raise SystemExit(f"parsed no sections out of {name}; has legal.ts changed shape?")
        return {
            "title": re.search(r'title: "([^"]+)"', block).group(1),
            "updated": updated.group(1) if updated else "",
            "sections": sections,
        }

    return {"version": version, "terms": doc("TERMS"), "privacy": doc("PRIVACY")}


def render(data: dict) -> str:
    return (
        HEADER
        + f"LEGAL_VERSION = {data['version']!r}\n\n"
        + f"TERMS = {json.dumps(data['terms'], indent=4)}\n\n"
        + f"PRIVACY = {json.dumps(data['privacy'], indent=4)}\n"
    )


if __name__ == "__main__":
    generated = render(parse(SOURCE.read_text()))
    TARGET.write_text(generated)
    print(f"wrote {TARGET.relative_to(ROOT)}")
