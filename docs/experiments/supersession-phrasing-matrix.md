# Experiment: when does supersession actually fire?

Run 2026-08-13/14 against the live hosted service (reeve 0.1.41,
`mistral.mistral-large-2407-v1:0`, all capabilities on). Each trial used a fresh
namespace, stored fact A, waited ~70s for indexing, stored the contradicting
fact B, waited ~85s, then read the raw retrieval context looking for the literal
` (superseded)` suffix the server appends to a replaced `State:` line.

## Result: it fires — but only when both sentences extract to the same key

**The mechanism works.** Trial 5 produced the marker, and everything downstream
of it, exactly as designed. The first four trials did not, and the difference
between them is the finding.

| # | Fact A | Fact B | Extracted | Marker |
|---|---|---|---|---|
| 1 | "The … report is due on 5 November." | "Prof. Nair moved the … deadline to 19 November." | `report.due date` and `report.deadline` | no |
| 2 | "The … report deadline is 5 November." | "The … report deadline is now 19 November." | State on A only; none for B | no |
| 3 | "The compiler design report deadline is 5 November." | "Prof. Nair moved the compiler design report deadline to 19 November." | `report.deadline` and `report.date` | no |
| 4 | "I live in Pune." | "I moved to Bangalore." | no States — only `Action` nodes | no |
| 5 | "Our runway is 18 months." | "Update: after the new hires, our runway is now 8 months." | `runway.duration` **and** `runway.duration` | **yes** |

Trial 5, in full:

```
[2026-08-14T07:01:14Z] Update: after the new hires, our runway is now 8 months.
  State: runway.duration = 8 months

[2026-08-14T07:00:02Z] Our runway is 18 months.
  State: runway.duration = 18 months (superseded)
```

## Diagnosis: parallel phrasing succeeds, divergent phrasing silently fails

Supersession is keyed on *(entity, attribute)*, and both halves of that key are
named by a language model reading the sentence. The key is only stable when both
sentences give the model the same shape to work from.

- **Trial 5 works** because A and B share a predicate form — "our runway is X" —
  so the attribute came out `duration` both times.
- **Trials 1 and 3 fail** because A and B use different verbs and framings
  ("is due on" vs "moved the deadline to"), and the model named the attribute
  from the phrasing: `due date`, `deadline`, `date`.
- **Trial 2 fails** because the near-duplicate second sentence produced no
  `State` at all.
- **Trial 4 fails** because the model chose `Action` nodes over `State` nodes,
  and Actions carry no supersession semantics.

So this is a robustness property, not a defect: the feature does what it claims,
and stops doing it when a probabilistic extractor feeds an exact-match key two
different names for one idea.

## The part that makes it hard to notice

In **every** trial — including the four where the mechanism never ran — the
answers were correct:

| Question | Answer |
|---|---|
| "When is the report due?" | 19 November |
| "When was the report originally due?" | 5 November |
| "What is our runway right now?" | 8 months |

That is the answer prompt instructing the model to "prefer the most recently
dated item", resolving currency from timestamps over two equally-active States.
It produces the same output supersession would, so from the answers alone the
two are indistinguishable — and a test that reads answers cannot tell whether
the mechanism ran.

## Consequences for this project

1. **The temporal claim is sound and is what the demo should rest on**: one
   store, both the current and the historical question, neither fact deleted.
2. **The `(superseded)` marker is worth showing when it appears, but the demo
   must not depend on it** — whether it appears depends on how the two sentences
   happen to be worded. The seeded corrections should use parallel phrasing to
   the facts they replace, and be verified before a demo rather than assumed.
3. The evidence panel renders the marker when present and degrades quietly when
   absent, which is the correct behaviour either way.

## A methodological note worth keeping

The first conclusion drawn from trials 1–4 was "supersession does not fire" —
and it was wrong, from four samples that happened to share a flaw: none used
parallel phrasing. Trial 5 reversed it. Two lessons, both cheap in hindsight:
a negative result across a narrow sample says more about the sample than the
system, and the fastest way to test a mechanism is to feed it the input its own
test suite uses.

Trials 1–2 also injected a unique token per run to isolate namespaces; that
distorted extraction badly enough that in trial 2 the token itself became the
entity. Later trials isolate by namespace only.
