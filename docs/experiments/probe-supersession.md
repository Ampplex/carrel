# Probe: state supersession

Run: `2026-08-13T18:06:45+00:00`

Namespace: `carrel-demo` · token `CARREL1786644405`

The claim under test: after a fact is replaced, the store can answer
both the present-tense and the historical question, and can say which
value is current. A nearest-neighbour index cannot — it holds two
equally plausible sentences with no relation between them.

1. Storing: The CARREL1786644405 mini-project report is due on 5 November.
   waiting 75s for the first write to index…
**context before the revision**

```
Long-term memory context (Reeve; use when not contradicted by short-term memory):
[2026-08-13T18:06:54.019Z] The CARREL1786644405 mini-project report is due on 5 November.  (summary: The CARREL1786644405 mini-project report is due on 5 November., emotion=neutral, importance=0.5)
  Entities: CARREL1786644405 mini-project report
  State: CARREL1786644405 mini-project report.due date = 5 November
```

2. Storing the contradiction: Prof. Nair moved the CARREL1786644405 mini-project report deadline to 19 November.
   waiting 75s for the second write to index…

| Question | Answer |
|---|---|
| When is the CARREL1786644405 report due? | The CARREL1786644405 mini-project report is due on 19 November. |
| When was the CARREL1786644405 report originally due? | The CARREL1786644405 mini-project report was originally due on 5 November. |

**raw context after the revision**

```
Long-term memory context (Reeve; use when not contradicted by short-term memory):
[2026-08-13T18:06:54.019Z] The CARREL1786644405 mini-project report is due on 5 November.  (summary: The CARREL1786644405 mini-project report is due on 5 November., emotion=neutral, importance=0.5)
  Entities: CARREL1786644405 mini-project report
  State: CARREL1786644405 mini-project report.due date = 5 November

[2026-08-13T18:08:15.191Z] Prof. Nair moved the CARREL1786644405 mini-project report deadline to 19 November.  (summary: Prof. Nair moved the CARREL1786644405 mini-project report deadline to 19 November., emotion=neutral, importance=0.5)
  Entities: CARREL1786644405 mini-project report, Prof. Nair
  Action: Prof. Nair moved → CARREL1786644405 mini-project report deadline
  State: CARREL1786644405 mini-project report.deadline = 19 November

Roles:
  Prof. Nair → professor
```

### Verdict

- PASS — current answer names 19 November
- PASS — current answer does NOT name 5 November
- PASS — historical answer names 5 November
- FAIL — context carries a literal `(superseded)` line

At least one check failed. Note that the narrated answers are model-dependent and the retrieval layer is the one that owns this property — a FAIL on an answer check with a PASS on the context check means the engine is right and the phrasing is off.
