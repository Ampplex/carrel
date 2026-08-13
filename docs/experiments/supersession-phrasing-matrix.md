# Experiment: when does supersession actually fire?

Run 2026-08-13 against the live hosted service (reeve 0.1.41,
`mistral.mistral-large-2407-v1:0`, all capabilities on). Each trial used a fresh
namespace, stored fact A, waited ~70s for indexing, stored the contradicting
fact B, waited ~85s, then read the raw retrieval context.

The thing being looked for is the literal ` (superseded)` suffix that the server
appends to a `State:` line whose fact has been replaced.

## Result: 0 of 4 trials produced a superseded marker

| # | Fact A | Fact B | What was extracted | Marker |
|---|---|---|---|---|
| 1 | "The … report is due on 5 November." | "Prof. Nair moved the … deadline to 19 November." | `report.due date = 5 November` and `report.deadline = 19 November` | no |
| 2 | "The … report deadline is 5 November." | "The … report deadline is now 19 November." | State on A only; B produced no State | no |
| 3 | "The compiler design report deadline is 5 November." | "Prof. Nair moved the compiler design report deadline to 19 November." | `compiler design report.deadline = 5 November` and `compiler design report.date = 19 November` | no |
| 4 | "I live in Pune." | "I moved to Bangalore." | no States at all — `Action: speaker lives → Pune`, `Action: speaker moved → Bangalore` | no |

Trials 1–3 also used a unique injected token (`CARREL<timestamp>`) to isolate
runs. That turned out to distort extraction — in trial 2 the token itself became
the entity (`CARREL1786644606.deadline`) — so trials 3 and 4 dropped it and
isolated by namespace instead. The failure persisted without it, so the token is
not the cause, but it is a reason to trust trials 3 and 4 more.

## Diagnosis

Supersession is keyed on the pair *(entity, attribute)*: storing a new `State`
with the same entity and the same attribute marks the previous one inactive and
draws a `SUPERSEDES` edge. That key is only as stable as the language model's
extraction, and across these trials the extraction was not stable:

- **the attribute name varied per call** for the same underlying concept —
  `due date`, `deadline`, `date`;
- **whether a `State` was emitted at all varied** — trial 2's second sentence
  produced none;
- **whether the fact became a `State` or an `Action` varied** — trial 4 produced
  only Actions, and Actions have no supersession semantics;
- **the entity name varied** — `compiler design report` in one episode,
  `Prof. Nair` in the next episode of the same trial.

Any one of these breaks the key. All four appeared within four trials.

## What still worked

In every trial the **answers were correct**:

| Question | Answer |
|---|---|
| "When is the report due?" | 19 November |
| "When was the report originally due?" | 5 November |
| "What is the compiler design report deadline?" | 19 November |
| "What was the … deadline originally?" | 5 November |

So the user-visible behaviour is right — but it is produced by the narrator
reasoning over timestamped episodes and an explicit recency instruction, **not**
by the supersession edge. The two are easy to confuse from the outside, which is
exactly why this was tested at the retrieval layer rather than by reading answers.

## Consequences for this project

The honest claim is narrower than the one the project started with, and the
demo must not point at a marker that will not be there:

1. **Do not build the viva around the `(superseded)` marker.** On this
   deployment it does not reliably appear for ordinary coursework phrasing.
2. **The temporal claim survives and is still worth making.** Both the current
   and the historical question get correct, different answers, from one store,
   without either sentence being deleted. A naive nearest-neighbour setup
   returns whichever sentence embeds closer and cannot reliably do both.
3. **This negative result is itself a finding**, and a more interesting one than
   a green tick: it locates the fragility precisely, at the point where a
   probabilistic extractor feeds a key that requires exact equality.

## Not established

- Whether supersession ever fires on this deployment. Four phrasings is a small
  sample and none were adversarially tuned toward the mechanism.
- Whether a more constrained capture format — the application proposing the
  attribute name rather than leaving it to free prose — would stabilise the key.
  That is the obvious next experiment and a genuine design idea to test.
- Whether behaviour differs on the self-hosted path or with a different chat
  model. Everything here is one account, one deployment, one afternoon.
