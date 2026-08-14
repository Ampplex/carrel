# Results

Measured against the live hosted service. Raw transcripts are in
`docs/experiments/`; nothing in this file is written by hand except the
interpretation.

Every table records the date of its run and the capability state at that moment.
The service is operator-controlled and can change underneath a result, which
would otherwise leave an old number quietly wrong.

## Environment at time of measurement

Run 2026-08-13. From `probe_config.py` (`docs/experiments/probe-config.md`):

| Field | Value |
|---|---|
| SDK | reeve 0.1.41 |
| provider / chat model | bedrock / `mistral.mistral-large-2407-v1:0` |
| embedding dimension | 1024 |
| vision enabled | yes |
| image retention | yes, indefinite |
| multimodal image search | yes |
| async writes | yes, worker running |
| geo enrichment | yes (unused by this project) |

Every capability this project depends on was live for all measurements below.

## 1. Read-after-write latency

The question: how long after a write is a memory actually findable, and is it
answerable before then via the short-term buffer?

Method: store a fact carrying a unique token; probe at 0, 10, 20, 40, 60 and 90
seconds; record whether the token appears at all, whether it appears under
`[PENDING - not yet indexed]`, and whether it appears as a real indexed episode.
Repeat at different times of day — the write buffer is per-process, so if the
hosted service runs multiple workers, visibility may vary between calls. A
non-deterministic result is itself a finding worth reporting.

Script: `backend/scripts/probe_readafterwrite.py`
Raw: `docs/experiments/probe-readafterwrite.md`

Run 2026-08-13, namespace `Carrel-probe`. `store_memory` returned
`{'pending_id': 'tmp_a9075e8e65', 'stored': False, 'persisting': True}`.

| t (s) | token in context | under PENDING | indexed episode | narrated answer |
|---|---|---|---|---|
| 8 | yes | yes | no | correct — "48 kilohertz" |
| 15 | yes | yes | yes | — |
| 22 | yes | no | yes | — |

**Finding: a write is answerable immediately, and fully indexed in about 20
seconds.** At t=8s the fact was not yet an indexed episode, but the narrated
answer was already correct — the server merges its short-term buffer of accepted
writes into the retrieval context, under a header instructing the model to prefer
it on conflict. By t=15s the memory existed in both places at once, and by t=22s
it had left the buffer entirely and lived in the graph.

Two things follow for the interface:

1. The pessimistic reading — "your write may not be findable yet" — is wrong for
   the first few seconds. It is findable; it is merely not yet *indexed*. The
   settling tray can honestly say a write is already answerable.
2. Indexing completed in roughly 20 seconds, against a documented window of 10 to
   60. Times were measured on an otherwise idle namespace; a busier account, or a
   burst of writes, should be expected to sit at the slower end.

**Caveat, and it matters: n = 1.** The server's write buffer is per-process, so
if the hosted service runs more than one worker, whether a caller sees their own
pending write may depend on which worker served the request. A single run cannot
distinguish "always visible" from "visible this time". This needs repeating
across several runs and times of day before the UI is redesigned around it — and
a non-deterministic result would itself be the finding.

## 2. Supersession and temporal correctness

Two claims were tested here, and they came apart. Full transcripts:
`docs/experiments/supersession-phrasing-matrix.md`.

### 2a. Does the store answer both the current and the historical question? Yes.

| Question | Answer |
|---|---|
| "When is the report due?" | 19 November |
| "When was the report originally due?" | 5 November |
| "What is the compiler design report deadline?" | 19 November |
| "What was the compiler design report deadline originally?" | 5 November |

Correct in every trial, from one store, with neither sentence deleted. This is
the claim the project makes, and it holds.

### 2b. Does the `SUPERSEDES` mechanism fire? Yes — when both facts extract to the same key. 1 of 5 trials.

Method: fresh namespace per trial; store fact A; wait ~70s for indexing; store
contradicting fact B; wait ~85s; read the raw retrieval context and look for the
literal ` (superseded)` suffix the server appends to a replaced `State:` line.

| # | Phrasing pair | Extracted | Marker |
|---|---|---|---|
| 1 | "is due on" / "moved the deadline to" | `report.due date` and `report.deadline` | no |
| 2 | "deadline is" / "deadline is now" | State on A only; none for B | no |
| 3 | "deadline is" / "Nair moved the deadline to" | `report.deadline` and `report.date` | no |
| 4 | "I live in Pune" / "I moved to Bangalore" | no States — only `Action` nodes | no |
| 5 | "our runway is 18 months" / "our runway is now 8 months" | `runway.duration` **twice** | **yes** |

**Diagnosis: parallel phrasing succeeds, divergent phrasing silently fails.**
Supersession is keyed on *(entity, attribute)* exact match, and both halves are
named by a language model reading the sentence. Trial 5's two sentences share a
predicate form, so the attribute came out `duration` both times and the mechanism
ran exactly as designed. Trials 1 and 3 used different verbs for the two halves
and got different attribute names for one idea; trial 2 produced no `State` for
its second sentence; trial 4 produced `Action` nodes, which have no supersession
semantics. Any one of those breaks the key.

**2a does not depend on 2b.** Correct temporal answers appeared in all five
trials, including the four where the mechanism never ran — the narrator resolves
currency from timestamps under an explicit recency instruction, producing the
same output supersession would. From the answers alone the two are
indistinguishable, which is exactly why this was asserted at the retrieval layer.

**Method note.** The first conclusion drawn here, from trials 1–4, was
"supersession does not fire". Trial 5 refuted it. The four samples shared a flaw —
none used parallel phrasing — and a negative result across a narrow sample says
more about the sample than the system. Trials 1–2 additionally injected a unique
token per run, which distorted extraction enough that in trial 2 the token became
the entity; later trials isolate by namespace only.

**Not established:** how often divergent phrasing occurs in genuine use, and
whether a capture format that proposes the attribute name rather than leaving it
to free prose would stabilise the key. One account, one model, five trials.

## 3. Photo re-interrogation

The claim: a question that nobody anticipated at upload time can be answered from
the retained original.

Method: for each of several photos with deliberately thin captions, ask questions
whose answers are absent from the stored description — attached and unattached —
and mark each correct or incorrect by hand.

This also produces this project's own measurement of the unattached image lane's
hit rate, to set against the roughly four-in-five figure the service documents.

| Photo | Question | Attached | Unattached | Correct? |
|---|---|---|---|---|
| _pending_ | | | | |

## 4. Cost

From `GET /api/health`, which reports the local query ledger.

| Category | Queries |
|---|---|
| development | _pending_ |
| rehearsal | _pending_ |
| demo | _pending_ |
| **total** | _pending_ |

Against a free-tier allowance of 20,000 queries and 1,000,000 tokens per month.
Note that storing a photo costs substantially more in tokens than storing text,
so the token budget binds sooner than the query budget.

## Interpretation

_To be written once the numbers exist._

## Limitations

See `architecture.md` §4 for inherited limits. Project-specific caveats:

- The context parser reads an internal rendering with no compatibility promise.
- Results are from a single account on a single deployment, over a period of
  days; they characterise this service as observed, not the design in general.
