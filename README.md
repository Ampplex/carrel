# Carrel

*A carrel is the private desk in a library where a student keeps their work.*

Coursework you can ask questions of. Capture lectures, decisions, deadlines,
whiteboard photographs and who is doing what; ask about them later in plain
language.

This is a college project built on the [Reeve](https://reeve.co.in) memory SDK.
It contains no Reeve server code — `reeve` is consumed from PyPI like any other
dependency, and this repository is entirely separate from the Reeve product
repositories.

---

## The argument

Storing coursework is easy. The hard part is that a term's worth of notes
contradicts itself, and the contradictions are the useful part.

A deadline moves. A supervisor changes. A project's scope is renegotiated in
week nine. A conventional search over your notes — including a vector search,
which is what most "chat with your documents" tools are — treats the old
sentence and the new one as two equally valid documents and returns whichever
one happens to sit closer to your question in embedding space. It has no notion
that one *replaced* the other.

Carrel is built to show what changes when the store does have that notion.

### Three things this does that a vector store cannot

**1. It knows which facts are stale.** When you say the deadline moved, Reeve
marks the previous value inactive, stamps it with the time it was replaced, and
draws a `SUPERSEDES` edge between the two. So *"when is the report due?"* and
*"when was it originally due?"* both have correct — and different — answers, and
the evidence panel shows the superseded value struck through. There is
deliberately no edit button in this app: restating something **is** the edit, and
an edit button would destroy the history that makes the second question
answerable.

**2. It can re-read a photograph.** A whiteboard photo is stored as one memory —
your caption fused with a vision model's description — plus an image vector, plus
the original image. Months later you can ask *"what was written in the top-right
corner?"* and get an answer, because the picture is looked at again at query
time. An embedding is a fingerprint: ideal for finding an image, useless for
reading one. A caption can only ever answer questions its author happened to
anticipate.

**3. It knows people from sentences.** Supervisors, teammates, courses and papers
become graph nodes with roles and relations, extracted from ordinary prose. The
People tab reads the graph rather than the narrated answer, because the edges are
exactly what a prose answer flattens away.

### And one thing it does that most demos don't

**It admits when it doesn't know yet.** Reeve accepts a write instantly and
finishes indexing it seconds later. During that window the app knows something
the user does not. Carrel puts every in-flight write in a permanent tray with a
live timer, refuses to call anything "indexed" on a timer alone — only an
explicit check, which costs a query and says so on the button, can do that — and
caveats every answer produced while writes are still settling.

---

## Running it

Requires Python 3.10+, Node 18+, and a Reeve API key from
[reeve.co.in](https://reeve.co.in).

```bash
# backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -e .
cp ../.env.example .env        # then edit .env and set REEVE_API_KEY
.venv/bin/uvicorn app.main:app --reload --port 8000

# frontend (separate terminal)
cd frontend
npm install
npm run dev                    # http://localhost:5173
```

For a demo, build the frontend instead and serve everything from one process:

```bash
cd frontend && npm run build   # backend then serves dist/ at http://localhost:8000
```

Tests run without touching the network or spending any quota:

```bash
cd backend && .venv/bin/python -m pytest tests/ -q
```

### The version pin matters

`pyproject.toml` requires `reeve>=0.1.41,<0.2`, and the lower bound is not
cosmetic:

- **0.1.40** added transparent reconnection when an idle session expires. A
  long-lived web backend is exactly the case the older behaviour broke.
- **0.1.41** added attached-photo arguments to the query calls. Photo
  re-interrogation does not exist below it.

The upper bound is there because two calls in `reeve_gateway.py` reach past the
published SDK surface — see the comments there for why.

Note that installing `reeve` also pulls in `neo4j`, `langchain`, `razorpay` and
`google-auth`: the published wheel declares the union of the client's and the
server's dependencies. Nothing here uses them. Use a virtualenv.

---

## How it is put together

```
browser ── fetch /api/* ──► FastAPI ── reeve SDK (SSE/JSON-RPC) ──► mcp.reeve.co.in
```

The API key never leaves the backend, and no endpoint accepts a namespace from
the client: the hosted server derives account identity from the key, but the
namespace half of the identity is whatever the caller passes, so letting a
browser choose it would let any browser read any namespace in the account. It
partitions data; it does not secure it.

| Path | What lives there |
|---|---|
| `backend/app/reeve_gateway.py` | the only module that imports `reeve` |
| `backend/app/parsers/context_parser.py` | turns raw retrieval context into typed blocks — the highest-value and most fragile module |
| `backend/app/errors.py` | classifies SDK failures into honest HTTP responses |
| `backend/app/pending.py` | the in-flight write registry behind the settling tray |
| `frontend/src/components/Evidence.tsx` | where a claim stops being a claim |

Design decisions and their reasoning are in [`docs/architecture.md`](docs/architecture.md).
The viva walkthrough is in [`docs/demo-script.md`](docs/demo-script.md).
Measured results go in [`docs/results.md`](docs/results.md).

---

## Deliberately not built

Tags, folders, an edit button, login, calendar sync. All generic CRUD, none of
it says anything about memory.

Possible extensions: a baseline vector-store comparison answering the same
questions side by side; a seeded evaluation set with pass/fail checks; a
two-namespace demo showing that the same name means different things to
different users.
