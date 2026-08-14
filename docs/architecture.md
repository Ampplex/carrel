# Architecture

## 1. The problem is memory, not search

Most "chat with your notes" projects are retrieval-augmented generation: embed
the documents, embed the question, return the nearest neighbours, let a language
model write a sentence. That works when the corpus is consistent.

A student's coursework is not consistent. It is a running argument with itself:
deadlines move, supervisors change, decisions get reversed in the next meeting.
The contradictions are not noise to be cleaned up — they are the record.

Nearest-neighbour retrieval has no way to represent *replacement*. Given

> The DSP mini-project report is due on 5 November.
> Prof. Nair moved the DSP mini-project report deadline to 19 November.

both sentences are excellent matches for "when is the report due?", and which one
comes back depends on wording, chunk boundaries and luck. The system cannot say
which is current, because "current" is not a property it stores.

This project is built on a store that keeps both sentences with their times and
reasons over them, so both "when is it due?" and "when was it originally due?"
are answerable. The whole design is oriented around making that difference
visible rather than merely claiming it — which is also how the project found that
one of its assumptions was wrong (§6).

## 2. System shape

```
┌────────── browser ──────────┐
│  React + TypeScript (Vite)  │
│  Desk · Photos · People      │
│  no API key, no namespace    │
└────────── fetch /api/* ──────┘
              │
┌─────────────▼───────────────────────────────────┐
│  FastAPI                                        │
│    routes/    thin HTTP layer                   │
│    reeve_gateway.py   ← the ONLY reeve importer  │
│    parsers/context_parser.py                    │
│    pending.py   quota.py   chunking.py          │
│    errors.py    classification table            │
└─────────────┬───────────────────────────────────┘
              │ synchronous SDK · SSE + JSON-RPC
┌─────────────▼───────────────────────────────────┐
│  mcp.reeve.co.in                                │
│  knowledge graph · vectors · vision · retained   │
│  images · Mistral Large                          │
└─────────────────────────────────────────────────┘
```

Reeve's graph is the database. This application deliberately has no database of
its own — the only local state is a display cache of uploaded photos, a registry
of in-flight writes, and a query ledger, none of which is a system of record.

## 3. Decisions worth defending

### 3.1 One module imports the SDK

`reeve_gateway.py` is the sole importer of `reeve`. Two reasons.

**Namespace ownership.** The hosted server composes identity as
`uid:namespace`. The `uid` comes from the API key and cannot be forged, but the
namespace is whatever the caller passes. If an HTTP handler accepted it from the
request body, any browser could read any namespace in the account. So no
function in the gateway takes a speaker argument at all; the namespace is a
server-side setting. A namespace partitions data. It does not secure it.

**Two calls reach past the published API.** The SDK's `store_memory` accepts
`image_base64`, but `query_memory`, `retrieve_memory_context` and
`search_image_memories` accept only `image_path` and `image_url` — while the MCP
tool underneath accepts base64 for all of them. A web backend holds uploaded
bytes in memory, so the published signature would force writing a temp file
purely to have the SDK read it back and base64 it. The gateway calls the tool
directly instead. Because that touches a private name, `reeve` is pinned
`>=0.1.41,<0.2` and both uses are confined to this one file.

### 3.2 Blocking SDK, async framework

The SDK is synchronous: `requests` plus a blocking queue read, with a timeout
measured in minutes. FastAPI handlers that do not need to await anything are
therefore written as plain `def`, which makes Starlette run them in its worker
threadpool automatically. This makes the safe path the default — a forgotten
`run_in_threadpool` inside an `async def` would stall the entire event loop for
every user, not just the caller. The two handlers that must await an upload are
`async def` and wrap each SDK call explicitly.

**Never two Reeve calls concurrently for one user action.** The SDK keeps one
cached client with one listener thread, and its stale-session recovery clears
every outstanding response queue when it fires — so a reconnect triggered by one
call can strand another that was in flight. Evidence mode asks, then retrieves,
sequentially.

**The connection is opened during startup**, not on the first request. The SDK's
connect guard is an unsynchronised boolean, so two simultaneous cold requests can
each start a listener thread; connecting once in the app's lifespan avoids that,
and keeps the handshake out of the first answer of a demo.

### 3.3 The context parser

`query_memory` returns prose. Prose is the thing an examiner is entitled to
distrust, and it is useless for building a UI. The raw context from
`retrieve_memory_context` is the only structured surface the SDK exposes, and it
is the layer that owns retrieval truth: the `(superseded)` markers, the
short-term block of not-yet-indexed writes, and the graph edges all live there
and are flattened away by the narrator.

It is also an internal rendering with no compatibility promise. Two consequences
shaped the module:

- **Tolerant parsing.** Unrecognised lines are preserved rather than dropped, and
  the raw string is always one click away in the UI. A format change must degrade
  the display, never lose the evidence.
- **Fixture-backed tests.** The grammar is pinned by unit tests that cost no
  quota, so an upstream change surfaces as a failing test rather than as a
  silently empty panel.

One genuine ambiguity is worth recording: actions render as `{actor} {verb}` with
no delimiter, so a multi-word actor like "Prof. Nair" cannot be split on
whitespace alone. The parser uses the episode's own `Entities:` line — emitted
before its actions — and takes the longest entity that the text starts with,
falling back to a first-space split when none matches.

### 3.4 Errors are a normal condition

The SDK erases exception types: server-side failures arrive as a `RuntimeError`
carrying a message string. Classification is therefore string matching against an
ordered table, which is unpleasant but is the real interface.

It matters because quota exhaustion and model throttling are *expected* states
here, not bugs, and they need to read differently in the UI. One case is worth
singling out: a rejected API key surfaces as a `ConnectionError` wrapping a 401,
so trusting the exception type would tell the user to check their network when
the actual fix is their credentials. The classifier inspects the message before
trusting the type — a mistake caught by running the app against a stale key
rather than by reasoning about it.

### 3.5 The async write contract

This is the section most student projects omit, because most hide the behaviour.

`store_memory` returns immediately with a pending pointer, and indexing completes
roughly ten to sixty seconds later. So there is a window in which a memory exists
but may not be findable, and the application knows it while the user does not.

Carrel's response:

- every in-flight write appears in a permanent tray with a live elapsed timer;
- statuses are careful — `indexing`, then `likely indexed` once enough time has
  passed, and `indexed` **only** after a check that actually looked;
- nothing is promoted to `indexed` by a timer, because `likely indexed` is a
  guess and `indexed` is a measurement, and conflating them is exactly the lie
  this design exists to avoid;
- any answer produced while writes are unsettled carries a visible caveat;
- the ask button is never disabled during indexing — hiding the window would
  hide the most interesting behaviour in the system.

There is **no background polling.** The tray's timers are local and make no
network calls; verification is user-triggered and prints its cost on the button.
This is a quota decision as much as an honesty one: an automatic poll every few
seconds would consume thousands of queries a day against a 20,000/month
allowance.

## 4. Inherited limits

Documented behaviour of the underlying service that this application must live
with, and does not pretend to have solved:

- **Long documents dilute retrieval.** One fact buried in a long brain-dump can
  lose to shorter, less relevant memories. Chunking is the application's job, so
  `chunking.py` splits on paragraph then sentence boundaries and prefixes each
  chunk with a shared context line.
- **The image lane prefers precision to recall.** Unattached photo questions
  miss roughly one time in five, and the lane declines to rank at all until the
  namespace holds at least three photos. The Photos tab shows attached and
  unattached answers side by side rather than only the flattering one.
- **Image retention is operator-controlled.** If it were switched off, photo
  re-interrogation would silently degrade to caption-only answers with no error.
  The capability badges read the live config so that failure is visible.
- **Model throttling under burst.** Writes are paced; reads are never fired
  concurrently.

## 5. What this project built, and what Reeve provides

| Reeve provides | Carrel builds |
|---|---|
| knowledge-graph extraction from prose | the capture surface, and the argument for having no edit button |
| timestamped episodes and a recency rule, which is what actually answers "now" vs "originally" | the evidence panel that shows both, so the answer can be checked rather than trusted |
| a supersession mechanism (`active:false`, `superseded_at`, `SUPERSEDES`) — **not observed firing**, see §6 | rendering for the marker when it appears, and no dependency on it when it does not |
| caption + vision fusion, image vectors, retained originals | the attached/unattached comparison that makes the capability legible |
| retrieval across several lanes | the tolerant parser that turns its output into structure |
| async writes with a pending buffer | the settling tray, the status vocabulary, the answer caveat |
| a synchronous Python SDK | the threading model, error classification, quota accounting |

## 6. An assumption that turned out to be wrong

The project began with three pillars. One of them did not survive contact with
measurement, and the way it failed is more instructive than the design that
preceded it.

**The assumption.** When a fact is replaced, Reeve marks the previous `State`
inactive, stamps `superseded_at`, and draws a `SUPERSEDES` edge; the retriever
then renders the old value with a literal ` (superseded)` suffix. The interface
was designed around putting that marker on screen — Reeve's own output, not this
application's rendering of it, which is what would make the claim checkable.

**What the measurement found.** Across four trials with different phrasings, on
fresh namespaces, the marker never appeared. The mechanism keys on
*(entity, attribute)* exact match, and the extraction that supplies that key is a
language model reading free prose. It was not stable: the same concept produced
the attributes `due date`, `deadline` and `date` on different runs; one sentence
produced no `State` at all; and the canonical "I live in X / I moved to Y" case
produced only `Action` nodes, which have no supersession semantics.

**Why it was nearly missed.** In every trial the *answers* were correct. Asking
"when is it due?" returned the new date and "when was it originally due?"
returned the old one. A project that checked its claims by reading answers would
have shipped believing the mechanism worked. The distinction only appears one
layer down, in the retrieval context — which is the reason the evidence panel and
the raw toggle exist at all, and the strongest practical argument in this whole
document for asserting at the layer that owns the property rather than at the
layer that narrates it.

**What changed as a result.** The claim narrowed to what is demonstrably true —
one store, both questions, neither fact deleted — and the demo no longer points
at a marker that will not be there. The interface still renders the marker if it
appears; it simply does not depend on it. The negative result is reported in full
in `docs/results.md`, because a located, diagnosed failure is worth more than an
untested assertion of success.

**The obvious next experiment**, not run here: have the capture surface propose
the attribute name rather than leaving it to free prose, and see whether a
stabilised key makes the mechanism fire. If it does, that is a real technique
rather than a workaround — it would say the mechanism is sound and the interface
to it is what needs constraining.
