# Screenshots — why they are not in this pack

Play requires at least two phone screenshots, and they are the part of a listing
people actually look at. They are missing here on purpose.

## What happened

The natural screenshots are the chat and the conversation drawer. Captured from
the phone, they contained:

- the owner's profile photograph and full name, in the drawer footer
- real conversation titles: *"What colour footwear I'm wearing"*, *"What is my
  favourite sport"*, *"Explain about today's activity"*
- the answers underneath them

A Play listing is public and effectively permanent — it is indexed, mirrored by
listing-scraper sites, and cached long after any edit. Those images were deleted
rather than shipped.

## The fix: a demo account

Screenshots should come from an account created for the purpose, holding
memories that illustrate the app without belonging to anybody.

1. **Make the account.** Sign up in the app with an address kept for this, or
   reuse the existing `reeve.co.in.ai@gmail.com`.

2. **Give it a handful of memories** that show what the app is for — something
   like:
   - *"The spare key is in the blue tin on the third shelf."*
   - *"Priya from the lab prefers to be emailed, not called."*
   - *"The Thursday seminar moved to room 214."* — then *"actually it moved back
     to 210"*, which demonstrates supersession in one screenshot
   - a photograph of a whiteboard or a printed page, then a question about a
     detail in it

3. **Capture four screens:**
   - the chat, mid-conversation, showing an answer
   - the same answer with *show what this came from* expanded — this is the most
     distinctive thing the app does and no competitor screenshot looks like it
   - the conversation drawer
   - Settings, showing that erasure is one tap away

4. **Check every pixel before uploading.** The status bar carries the time and
   battery, which is fine; what matters is that no name, face or real memory
   belonging to a person appears anywhere.

## Requirements

| | |
|---|---|
| Minimum | 2 screenshots; 4–8 is better |
| Size | 1080 × 2400 is what this phone produces, and is accepted |
| Format | PNG or JPEG, no alpha |
| Aspect | Between 16:9 and 9:16 |

To capture one, with the device connected:

```
adb exec-out screencap -p > screen-1.png
```
