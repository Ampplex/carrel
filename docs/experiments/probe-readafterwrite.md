# Probe: read-after-write latency

Run: `2026-08-13T18:06:01+00:00`

Namespace: `carrel-probe`
Token: `CARREL1786644361`

Stored fact: The CARREL1786644361 lab meeting decided the sampling rate for the DSP mini-project is 48 kilohertz.
Question: What sampling rate did the CARREL1786644361 lab meeting decide on?

**store_memory returned**

```
{'pending_id': 'tmp_a9075e8e65', 'speaker': 'google-oauth2|101989921549854916710:carrel-probe', 'stored': False, 'persisting': True}
```

| t (s) | token in context | under PENDING | indexed episode | narrated answer |
|---|---|---|---|---|
| 8 | yes | yes | no | The CARREL1786644361 lab meeting decided on a sampling rate … |
| 15 | yes | yes | yes | — |
| 22 | yes | no | yes | — |
**full context at t=22s**

```
Long-term memory context (Reeve; use when not contradicted by short-term memory):
[2026-08-13T18:06:13.507Z] The CARREL1786644361 lab meeting decided the sampling rate for the DSP mini-project is 48 kilohertz.  (summary: The CARREL1786644361 lab meeting decided the sampling rate for the DSP mini-project is 48 kilohertz., emotion=neutral, importance=0.7)
  Entities: CARREL1786644361, DSP mini-project
  Action: CARREL1786644361 decided → sampling rate for the DSP mini-project is 48 kilohertz
  State: DSP mini-project.sampling rate = 48 kilohertz
```


Interpretation: if the token appears at t=0 under PENDING, the app may tell the user their write is already answerable. If it only appears once the episode is indexed, the UI must never imply otherwise.
