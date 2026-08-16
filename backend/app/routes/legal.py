"""Publicly readable Terms and Privacy Policy.

The only unauthenticated pages this server has, and deliberately so. Google will
not let an OAuth consent screen leave Testing without a privacy policy at a URL
anyone can open — and more to the point, a policy that can only be read from
inside the app is not much of a policy. Somebody deciding whether to sign up
cannot see it, and nobody can link to it.

The words come from app/legal_content.py, generated from the app's own copy, so
what is published here and what somebody taps "agree" to in the app cannot
quietly diverge.

Rendered as plain HTML with no JavaScript, no fonts, no analytics, and nothing
loaded from another host. A privacy policy that phones a tracker while you read
it is its own argument.
"""

from __future__ import annotations

from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.legal_content import LEGAL_VERSION, PRIVACY, TERMS

router = APIRouter()

_STYLE = """
:root { color-scheme: light dark; }
body {
  margin: 0 auto; padding: 2.5rem 1.25rem 5rem; max-width: 42rem;
  font: 16px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: #ffffff; color: #1a1c1a;
}
@media (prefers-color-scheme: dark) {
  body { background: #0f110f; color: #e8eae8; }
  a { color: #7fd1ae; }
  .meta, footer { color: #8d938d; }
  h2 { color: #cfd4cf; }
}
h1 { font-size: 1.75rem; letter-spacing: -0.02em; margin: 0 0 0.4rem; }
h2 { font-size: 1.05rem; margin: 2.25rem 0 0.5rem; }
p { margin: 0 0 1rem; }
.meta { color: #6b706b; font-size: 0.9rem; margin-bottom: 2.5rem; }
a { color: #1f7a53; }
footer {
  margin-top: 4rem; padding-top: 1.25rem; border-top: 1px solid rgba(128,128,128,0.25);
  font-size: 0.875rem; color: #6b706b;
}
"""


def _page(doc: dict, other_path: str, other_label: str) -> str:
    sections = "\n".join(
        f"<h2>{escape(s['heading'])}</h2>\n<p>{escape(s['body'])}</p>"
        for s in doc["sections"]
    )
    updated = escape(doc.get("updated") or LEGAL_VERSION)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(doc['title'])} · Carrel</title>
<style>{_STYLE}</style>
</head>
<body>
<h1>{escape(doc['title'])}</h1>
<p class="meta">Version {escape(LEGAL_VERSION)} · last updated {updated}</p>
{sections}
<footer>
<p><a href="{other_path}">{escape(other_label)}</a></p>
<p>Questions, or want your data removed? The app can erase everything itself,
immediately, from Settings — but you can also write to
<a href="mailto:ankesh3905222@gmail.com">ankesh3905222@gmail.com</a>.</p>
</footer>
</body>
</html>
"""


# Cached for a day: these change rarely, and an unauthenticated page on a public
# host will be fetched by every crawler that finds it.
_HEADERS = {"Cache-Control": "public, max-age=86400"}


@router.get("/legal/privacy", response_class=HTMLResponse)
def privacy() -> HTMLResponse:
    return HTMLResponse(_page(PRIVACY, "/legal/terms", "Terms of Use"), headers=_HEADERS)


@router.get("/legal/terms", response_class=HTMLResponse)
def terms() -> HTMLResponse:
    return HTMLResponse(_page(TERMS, "/legal/privacy", "Privacy Policy"), headers=_HEADERS)
