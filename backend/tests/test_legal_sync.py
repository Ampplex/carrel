"""The published policy must be the one people agreed to. Zero quota.

The app embeds its own copy of the Terms and Privacy Policy so it works offline
and so the wording somebody accepted is the wording their build showed them. The
server has a second copy, because Google requires a publicly reachable privacy
policy URL and because a policy only readable inside the app cannot be linked to
or read before signing up.

Two copies of the same document is the arrangement that goes wrong quietly: one
gets edited, the other does not, and the stale one is always the published one.
So the copy is generated (scripts/sync_legal.py) and this fails if it is stale.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from sync_legal import SOURCE, parse, render  # noqa: E402

from app import legal_content  # noqa: E402


def test_the_server_copy_is_not_stale():
    """If this fails: `cd backend && python scripts/sync_legal.py`."""
    expected = render(parse(SOURCE.read_text()))
    actual = (pathlib.Path(legal_content.__file__)).read_text()

    assert actual == expected, (
        "app/legal_content.py is out of date with mobile/src/legal.ts. "
        "Regenerate it: cd backend && python scripts/sync_legal.py"
    )


def test_versions_agree():
    """The version is recorded against every account at sign-up, so a mismatch
    means accounts are stamped with a version that does not describe what they
    were shown."""
    source = SOURCE.read_text()
    assert f'LEGAL_VERSION = "{legal_content.LEGAL_VERSION}"' in source


def test_both_documents_have_content():
    """A parser that silently produces an empty document would publish a blank
    page that still returns 200."""
    for doc in (legal_content.TERMS, legal_content.PRIVACY):
        assert doc["title"]
        assert len(doc["sections"]) >= 5
        for section in doc["sections"]:
            assert section["heading"].strip()
            assert len(section["body"].strip()) > 40


def test_the_pages_are_reachable_without_a_token():
    """The whole point. A privacy policy behind authentication is unreadable by
    exactly the people deciding whether to hand over their data."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    for path in ("/legal/privacy", "/legal/terms"):
        response = client.get(path)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


def test_the_pages_load_nothing_from_anywhere_else():
    """No scripts, no remote fonts, no analytics. A privacy policy that phones a
    tracker while you read it is its own argument."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    for path in ("/legal/privacy", "/legal/terms"):
        body = client.get(path).text
        assert "<script" not in body.lower()
        assert "http://" not in body
        # The only external reference allowed is a mailto: for data requests.
        assert "https://" not in body.replace("https://carrel.reeve.co.in", "")
