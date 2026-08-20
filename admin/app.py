"""One page showing the state of Reeve and Carrel, for the person who runs them.

Carrel keeps accounts in Postgres; Reeve keeps its graph and its billing plans
in Neo4j. Neither knows the other exists — Carrel holds a namespace and Reeve
holds episodes filed under that namespace, and nothing joins them. Answering
"how many people actually use this, and how much have they stored" therefore
meant two shells and a lot of typing. This is that question, answered on one
page.

WHAT IT DELIBERATELY DOES NOT DO

It never shows a memory. Not a note, not a caption, not a chat message. The
privacy policy this product ships with says a person's memories are theirs, and
an admin console that quietly makes them readable would turn that into a lie
that happens to be convenient for me. Counts and dates answer every operational
question worth asking — is anyone signing up, is anything failing, is a write
stuck — and none of them require reading what somebody wrote about their own
life.

It is also read-only. There is no delete button, no plan override, no key
revocation. Those are real needs, and they belong behind something better than
"whoever reached this page", which today is "whoever is on the server".

HOW IT IS REACHED

Bound to 127.0.0.1 and NOT proxied by nginx, so it has no public address at all.
From a laptop:

    ssh -i ~/reeve.pem -L 8020:127.0.0.1:8020 ubuntu@<host>
    open http://localhost:8020

That places it behind the SSH key rather than behind a password I would have had
to invent, store and eventually leak. The moment this page needs to be reachable
without a tunnel, it needs real authentication first — not after.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

load_dotenv(Path(__file__).resolve().parent / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
NEO4J_URI = os.environ.get("NEO4J_URI", "")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")

app = FastAPI(title="Reeve + Carrel admin", docs_url=None, redoc_url=None)


# ── data access ───────────────────────────────────────────────────────────────


@contextmanager
def pg():
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=5) as conn:
        yield conn


def carrel_stats() -> dict:
    """Everything Carrel knows, as counts. No message or note text is selected."""
    out: dict = {"ok": True}
    try:
        with pg() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM users")
            out["users"] = cur.fetchone()["n"]

            cur.execute("SELECT count(*) AS n FROM users WHERE password_hash IS NULL")
            out["google_only"] = cur.fetchone()["n"]

            cur.execute("SELECT count(*) AS n FROM users WHERE email_verified")
            out["verified"] = cur.fetchone()["n"]

            cur.execute("SELECT count(*) AS n FROM sessions")
            out["sessions"] = cur.fetchone()["n"]

            for table in ("chats", "messages", "photos"):
                cur.execute(f"SELECT count(*) AS n FROM {table}")
                out[table] = cur.fetchone()["n"]

            # The settling tray is the best early warning this system has: a
            # write that never left "indexing" is a memory somebody believes
            # they stored and cannot retrieve.
            cur.execute(
                "SELECT status, count(*) AS n FROM pending_writes GROUP BY status ORDER BY status"
            )
            out["pending"] = {r["status"]: r["n"] for r in cur.fetchall()}

            cur.execute(
                "SELECT count(*) AS n FROM login_failures "
                "WHERE at > %s",
                (time.time() - 24 * 3600,),
            )
            out["login_failures_24h"] = cur.fetchone()["n"]

            cur.execute("SELECT count(*) AS n FROM bounced_addresses")
            out["bounced"] = cur.fetchone()["n"]

            # Signups over time, so "is anyone actually using this" has an answer
            # that is not a vibe.
            cur.execute(
                "SELECT count(*) FILTER (WHERE created_at > %s) AS d1,"
                "       count(*) FILTER (WHERE created_at > %s) AS d7,"
                "       count(*) FILTER (WHERE created_at > %s) AS d30 FROM users",
                (time.time() - 86400, time.time() - 7 * 86400, time.time() - 30 * 86400),
            )
            row = cur.fetchone()
            out["signups"] = {"24h": row["d1"], "7d": row["d7"], "30d": row["d30"]}

            # Per-account rows. Email is shown because it IS the account
            # identifier and this page exists to administer accounts; nothing
            # they have written is shown beside it.
            cur.execute(
                """
                SELECT u.email, u.name, u.namespace, u.created_at, u.email_verified,
                       (u.password_hash IS NULL) AS google_only,
                       (SELECT count(*) FROM chats c WHERE c.namespace = u.namespace) AS chats,
                       (SELECT count(*) FROM photos p WHERE p.namespace = u.namespace) AS photos,
                       (SELECT count(*) FROM sessions s WHERE s.email = u.email) AS sessions
                FROM users u ORDER BY u.created_at DESC
                """
            )
            out["accounts"] = cur.fetchall()
    except Exception as exc:  # noqa: BLE001 - the page must render without Postgres
        out = {"ok": False, "error": str(exc)[:200]}
    return out


def reeve_stats() -> dict:
    """Reeve's side: plans, keys, and how much is actually in the graph."""
    out: dict = {"ok": True}
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD), connection_timeout=10
        )
        with driver.session() as s:
            out["users"] = s.run("MATCH (u:User) RETURN count(u) AS n").single()["n"]
            out["with_key"] = s.run(
                "MATCH (u:User) WHERE u.api_key_hash IS NOT NULL RETURN count(u) AS n"
            ).single()["n"]
            out["plans"] = {
                r["plan"] or "free": r["n"]
                for r in s.run(
                    "MATCH (u:User) RETURN coalesce(u.plan,'free') AS plan, count(*) AS n "
                    "ORDER BY n DESC"
                )
            }
            out["episodes"] = s.run("MATCH (e:Episode) RETURN count(e) AS n").single()["n"]
            out["entities"] = s.run("MATCH (n:Entity) RETURN count(n) AS n").single()["n"]
            out["photo_episodes"] = s.run(
                "MATCH (e:Episode) WHERE e.image_key IS NOT NULL RETURN count(e) AS n"
            ).single()["n"]
            # Episodes per speaker: the only view that shows which namespaces are
            # actually carrying data. Speaker is an opaque hash, not an email.
            out["top_speakers"] = [
                {"speaker": r["speaker"], "episodes": r["n"]}
                for r in s.run(
                    "MATCH (e:Episode) RETURN e.speaker AS speaker, count(*) AS n "
                    "ORDER BY n DESC LIMIT 15"
                )
            ]
            out["recent_24h"] = s.run(
                "MATCH (e:Episode) WHERE e.timestamp > datetime() - duration({hours:24}) "
                "RETURN count(e) AS n"
            ).single()["n"]
        driver.close()
    except Exception as exc:  # noqa: BLE001
        out = {"ok": False, "error": str(exc)[:200]}
    return out


# ── rendering ─────────────────────────────────────────────────────────────────


def _ago(epoch: float | None) -> str:
    if not epoch:
        return "—"
    delta = time.time() - float(epoch)
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if delta >= size:
            return f"{int(delta // size)}{unit} ago"
    return "just now"


def _stat(label: str, value, sub: str = "") -> str:
    sub_html = f'<div class="sub">{sub}</div>' if sub else ""
    return f'<div class="stat"><div class="n">{value}</div><div class="l">{label}</div>{sub_html}</div>'


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Reeve + Carrel</title>
<style>
  :root {{
    --bg:#0d0c0a; --card:#171613; --line:#2c2823; --ink:#ede8de;
    --dim:#a69e90; --faint:#6f6759; --accent:#8fb9a8; --warn:#d7a34c; --bad:#d98872;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; padding:32px 24px 64px; }}
  .wrap {{ max-width:1100px; margin:0 auto; }}
  h1 {{ font-size:22px; margin:0 0 4px; letter-spacing:-.3px; }}
  .meta {{ color:var(--faint); font-size:13px; margin-bottom:28px; }}
  h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.08em;
    color:var(--dim); margin:32px 0 12px; font-weight:600; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }}
  .stat {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }}
  .stat .n {{ font-size:26px; font-weight:600; letter-spacing:-.5px; }}
  .stat .l {{ color:var(--dim); font-size:12.5px; margin-top:2px; }}
  .stat .sub {{ color:var(--faint); font-size:11.5px; margin-top:6px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13.5px; }}
  .scroll {{ overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:12px; }}
  th {{ text-align:left; color:var(--dim); font-weight:600; font-size:11.5px;
    text-transform:uppercase; letter-spacing:.05em; padding:12px 14px; border-bottom:1px solid var(--line); }}
  td {{ padding:11px 14px; border-bottom:1px solid var(--line); white-space:nowrap; }}
  tr:last-child td {{ border-bottom:none; }}
  .mono {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12.5px; color:var(--dim); }}
  .tag {{ font-size:11px; padding:2px 7px; border-radius:99px; border:1px solid var(--line); color:var(--dim); }}
  .ok {{ color:var(--accent); }} .warn {{ color:var(--warn); }} .bad {{ color:var(--bad); }}
  .err {{ background:#241512; border:1px solid #4a2a22; color:var(--bad);
    padding:12px 14px; border-radius:10px; font-size:13px; }}
  .note {{ color:var(--faint); font-size:12px; margin-top:10px; }}
  .num {{ text-align:right; }}
</style></head>
<body><div class="wrap">
<h1>Reeve + Carrel</h1>
<div class="meta">{generated} · read-only · localhost only</div>
{body}
<div class="note">Counts only. No note, caption or message text is read by this page —
the privacy policy says those belong to the person who wrote them.</div>
</div></body></html>"""


def render(carrel: dict, reeve: dict) -> str:
    parts: list[str] = []

    parts.append("<h2>Carrel — accounts (Postgres)</h2>")
    if not carrel.get("ok"):
        parts.append(f'<div class="err">Postgres unreachable: {carrel.get("error")}</div>')
    else:
        s = carrel["signups"]
        pend = carrel.get("pending", {})
        stuck = pend.get("indexing", 0) + pend.get("likely_indexed", 0)
        failed = pend.get("failed", 0)
        parts.append(
            '<div class="grid">'
            + _stat("accounts", carrel["users"], f'{carrel["google_only"]} Google · {carrel["verified"]} verified')
            + _stat("new signups", s["30d"], f'{s["24h"]} today · {s["7d"]} this week')
            + _stat("conversations", carrel["chats"], f'{carrel["messages"]} messages')
            + _stat("photos", carrel["photos"])
            + _stat("live sessions", carrel["sessions"])
            + _stat(
                "writes settling",
                f'<span class="{"warn" if stuck else "ok"}">{stuck}</span>',
                f'{failed} failed' if failed else "none failed",
            )
            + _stat(
                "failed logins 24h",
                f'<span class="{"warn" if carrel["login_failures_24h"] > 20 else ""}">{carrel["login_failures_24h"]}</span>',
                f'{carrel["bounced"]} bounced addresses',
            )
            + "</div>"
        )

        def account_row(a: dict) -> str:
            kind = "Google" if a["google_only"] else "password"
            verified = '<span class="tag ok">verified</span>' if a["email_verified"] else ""
            return (
                "<tr>"
                f'<td>{a["email"]}</td>'
                f'<td>{a["name"] or "—"}</td>'
                f'<td><span class="tag">{kind}</span> {verified}</td>'
                f'<td class="mono">{a["namespace"]}</td>'
                f'<td class="num">{a["chats"]}</td>'
                f'<td class="num">{a["photos"]}</td>'
                f'<td class="num">{a["sessions"]}</td>'
                f'<td class="mono">{_ago(a["created_at"])}</td>'
                "</tr>"
            )

        rows = "".join(account_row(a) for a in carrel["accounts"])
        parts.append(
            '<div class="scroll"><table><tr>'
            "<th>Email</th><th>Name</th><th>Sign-in</th><th>Namespace</th>"
            '<th class="num">Chats</th><th class="num">Photos</th>'
            '<th class="num">Sessions</th><th>Joined</th></tr>'
            f"{rows}</table></div>"
        )

    parts.append("<h2>Reeve — memory graph (Neo4j)</h2>")
    if not reeve.get("ok"):
        parts.append(f'<div class="err">Neo4j unreachable: {reeve.get("error")}</div>')
    else:
        plans = " · ".join(f"{n} {p}" for p, n in reeve["plans"].items()) or "—"
        parts.append(
            '<div class="grid">'
            + _stat("Reeve users", reeve["users"], f'{reeve["with_key"]} with API keys')
            + _stat("plans", len(reeve["plans"]), plans)
            + _stat("episodes", f'{reeve["episodes"]:,}', f'{reeve["recent_24h"]} in last 24h')
            + _stat("entities", f'{reeve["entities"]:,}')
            + _stat("photo memories", reeve["photo_episodes"])
            + "</div>"
        )
        rows = "".join(
            f'<tr><td class="mono">{t["speaker"]}</td><td class="num">{t["episodes"]:,}</td></tr>'
            for t in reeve["top_speakers"]
        )
        parts.append(
            '<div class="scroll"><table>'
            '<tr><th>Speaker (namespace)</th><th class="num">Episodes</th></tr>'
            f"{rows}</table></div>"
        )

    return "\n".join(parts)


@app.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    carrel, reeve = carrel_stats(), reeve_stats()
    generated = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    return HTMLResponse(PAGE.format(generated=generated, body=render(carrel, reeve)))


@app.get("/api/stats")
def stats() -> JSONResponse:
    """The same numbers as JSON, for when a graph is wanted elsewhere."""
    return JSONResponse({"carrel": carrel_stats(), "reeve": reeve_stats()})


@app.get("/health")
def health() -> dict:
    return {"ok": True}
