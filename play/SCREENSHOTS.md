# Screenshots

All captured 18 Aug 2026 from the **demo account** (`tester.reeve.co.in.ai@gmail.com`)
on the RMX3782 at 1080x2400, over adb. No face, no real name, no personal
memory appears in any frame; the one address that did appear (Settings) is
blurred. Seeded content is deliberately non-Indian and student-flavoured.

The finished files are in `screenshots/`, named in the order they should appear
in the listing:

| # | File | What it shows |
|---|---|---|
| 1 | `a1-say-it.png` | Onboarding — "Just say it" |
| 2 | `a2-corrections.png` | Onboarding — "Corrections are memories too" |
| 3 | `a3-photograph.png` | Onboarding — "Photograph anything" |
| 4 | `a4-seminar-moved-twice.png` | The two contradictory stores: moved to 214, then back to 210 |
| 5 | `a5-latest-wins.png` | "Where is the Thursday seminar?" → room 210 — the correction wins |
| 6 | `a6-shows-its-working.png` | The same answer with its 6 source memories expanded |
| 7 | `a7-asked-later.png` | A *separate* conversation, no photo attached: the blue folder, the charger, 16:00 — all read off the photographed whiteboard |
| 8 | `a8-your-data.png` | Settings: erase everything, delete account |

## Two frames were deliberately dropped

- **Photo attached, then asked about it in the same thread.** It proves only
  that the model can read an image handed to it a second earlier. Frame 7 is
  the real claim: the photo is gone from view, the conversation is different,
  and the detail still comes back.
- **A rambling four-point answer** that ignored the whiteboard and rendered raw
  `**markdown**` asterisks. Both are defects, not features — see below.

## What the screenshots forced us to fix

Frame 7 did not work at first. Asked "who is speaking on 13 November?", Carrel
said **"I don't remember"** while holding a photo that says so in handwriting.

Cause, in Reeve: `IMAGE_MEMORY_PROMPT` folded "any visible readable text" into a
2-4 sentence description, so a timetable became "a whiteboard with blue and red
writing listing a seminar series" and every name, date and room number was gone
before it reached the graph. The retrieval gate made it worse — the ambient
image lane needs `IMAGE_LANE_MIN_SAMPLE` (3) photos to find a break in the
ranking, so an account with one photo never re-reads it, and the gate's excuse
("the text lanes still retrieve it through its description") only holds if the
description carries the detail.

Fixed in `llm-three-lane-memory` commit 07c8358 — the prompt now transcribes
readable text verbatim under a `TEXT:` line, with its own token budget so a
long transcript is not cut mid-row. Deployed to production, photo re-stored,
and the same question now answers correctly.

## Still open

The app renders answers as plain text with **no markdown handling**, so any
`**bold**` or numbered list the model emits shows up as literal asterisks.
