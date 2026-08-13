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

Run 2026-08-13, namespace `carrel-probe`. `store_memory` returned
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

## 2. Supersession

The claim: the store knows which of two contradictory facts replaced the other.

Method: store a fact, wait for indexing, store a contradicting fact, wait again,
then ask both the present-tense and the historical question and capture the raw
retrieval context verbatim.

| Question | Answer | Raw `State:` line |
|---|---|---|
| _pending_ | | |

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
