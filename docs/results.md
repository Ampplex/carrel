# Results

> **Status: not yet measured.** Every table below is a placeholder waiting on a
> working API key. Nothing here should be written by hand — the whole point is
> that the numbers come from real runs of the deployed service, captured into
> `docs/experiments/` and quoted verbatim.

Record with every table: the date of the run and the `memory_config()` output
captured at that moment. The hosted service is operator-controlled and can change
underneath a result, which would otherwise make an old number quietly wrong.

## Environment at time of measurement

Capture from `GET /api/config`:

| Field | Value |
|---|---|
| chat model | _pending_ |
| vision enabled | _pending_ |
| image retention | _pending_ |
| multimodal image search | _pending_ |
| async writes | _pending_ |

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

| t (s) | token in context | under PENDING | indexed episode | narrated answer |
|---|---|---|---|---|
| _pending_ | | | | |

Median time to indexed: _pending_ (n = _pending_)

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
