# Demo script

Two acts, roughly six minutes, about twelve queries. Each act ends on a moment
where the claim is visible on screen in the system's own output rather than in
the presenter's narration.

## Preconditions

Do these **at least a day before**, never live:

- Seed the namespace with about thirty memories, including **at least four
  photos** — the image lane declines to rank at all below three, so the
  unattached comparison in Act 2 cannot work without them.
- Include at least two deliberate supersessions.
- Verify every seeded write reached `indexed`.
- Then leave the namespace alone except for the live beat in Act 1.
- On the morning of: open the app and check the capability badges are green.
  Photo retention is operator-controlled and could have changed.

## Act 1 — the system knows which fact is stale

Pre-seeded, days earlier:

> The DSP mini-project report is due on 5 November.

1. **Live, on stage:** type *"Prof. Nair moved the DSP mini-project report
   deadline to 19 November."* and press Remember this.

   A pending chip appears in the tray with a running timer. Say it out loud:
   *"note that it is not indexed yet — the app is telling you so rather than
   pretending."* This beat is the honesty credential, and it costs nothing.

2. While it settles, ask **"When is the DSP report due?"**

   Either answer is fine here, because the caveat banner is on screen. Narrate
   whichever happens: if it already knows, Reeve is answering from its short-term
   buffer; if it does not, the app said so in advance.

3. Fill about a minute with the architecture diagram, then click **check now** on
   the pending chip. It turns green — and note that only this click could turn it
   green, because it is the only thing that actually looked.

4. Ask **"When is the DSP report due?"** → *19 November.*

5. Ask **"When was the DSP report originally due?"** → *5 November.*

6. Click **Ask + show evidence**, then **Show raw context**.

   Both `State:` lines are visible, one ending in the literal ` (superseded)`.

> *"A vector store keeps both sentences and returns whichever one embeds closer
> to the question. It has no way to say which replaced the other. Reeve decided
> that at write time — the old fact is marked inactive, stamped with when it was
> replaced, and joined to the new one by a SUPERSEDES edge — so both questions
> have correct answers, and they are different answers."*

The raw toggle matters: what is on screen is Reeve's own output, not this
application's rendering of it.

## Act 2 — the system can re-read a photograph

Pre-seeded, weeks earlier: a whiteboard photo with a deliberately thin caption —
*"whiteboard from the Tuesday lab meeting."*

1. Open Photos and select it. Point out what was stored: the caption fused with a
   vision description into **one** memory. Read the description aloud and note
   that it says nothing about the top-right corner.

2. Ask a question nobody could have anticipated when that caption was written:
   **"what was written in the top-right corner?"**

   The attached answer comes from the vision model looking at the retained
   original again, at query time.

3. The unattached answer appears beside it. If the lane fired, both agree — the
   photo was found on its own merits. If it did not, say so plainly: the lane is
   tuned to prefer precision over recall and misses roughly one in five. Showing
   the miss is worth more than hiding it.

4. Search *"whiteboard with a state diagram"* — found by how it looks, not by
   what its caption says.

> *"The caption was written once, by whoever uploaded the photo. The image is
> read again every time it is asked about. An index over captions can only ever
> answer the questions the captioner happened to anticipate."*

## If something goes wrong

- **Model throttling** is the likeliest failure and shows as a "throttled, try
  again in a few seconds" message. Wait and retry; do not hammer it.
- **Quota** is not a realistic risk — the whole demo is about twelve queries
  against a monthly allowance of twenty thousand — but the usage figures are in
  `/api/health` if asked.
- Keep a screen recording of a clean rehearsal run. If the network fails, show
  the recording and say that is what it is.

## Cost

About 12 queries live, plus roughly 35 across two rehearsals. Every ask prints
its own cost on the button, and the running total is in `/api/health`.
