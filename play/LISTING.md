# Carrel — Google Play listing

Everything Play asks for, written out. Copy each block into the console field it
names. Where a field has a hard character limit, the count is given.

---

## App details

| Field | Value |
|---|---|
| App name | `Carrel` |
| Package | `com.ampplex.carrel` |
| Default language | English (United Kingdom) |
| App or game | App |
| Category | Productivity |
| Contact email | `ankeshpune@gmail.com` |
| Privacy policy | `https://carrel.reeve.co.in/legal/privacy` |
| Website (optional) | `https://carrel.reeve.co.in/legal/terms` |

---

## Short description

*Play limit: 80 characters. This is 72.*

```
A memory for the things you'll need later. Just say it, and ask later.
```

---

## Full description

*Play limit: 4000 characters. This is about 1,500.*

```
Carrel remembers the things you would otherwise write on the back of your hand.

Tell it in plain words — the name of the person you just met, the room your exam
is in, where you put your passport, what your landlord agreed to on the phone.
Later, ask in plain words too. There are no folders to choose, no tags to invent
and no format to learn.

PHOTOGRAPHS, NOT JUST CAPTIONS

Photograph a whiteboard, a slide, a receipt or a room. Carrel keeps the picture
itself, not only what you typed about it, so months later you can ask about a
detail nobody thought to write down at the time.

CORRECTIONS ARE MEMORIES TOO

Say "actually it moved to Thursday" and Carrel keeps both — what you said before
and what you say now — so an answer can tell you what changed rather than
quietly pretending the old version never existed.

IT TELLS YOU WHAT IT IS UNSURE OF

A memory takes a moment to become findable after you store it. Most apps hide
that. Carrel shows it: a note that has just been saved is marked as still
settling, and an answer that might be missing something says so. When it claims
a memory is stored, it has checked.

SHOW YOUR WORKING

Every answer can show the memories it came from, with dates, so you can see why
Carrel said what it said instead of taking its word for it.

YOUR DATA IS YOURS

Everything you store belongs to your account alone. Settings can erase all of it
— notes, photographs and conversations — immediately, with no grace period and
no copy retained. Deleting your account removes the login as well.

Carrel needs an internet connection: your memories live on a server, not only on
the phone, so they survive losing the device.
```

---

## Graphics

| Asset | File | Size |
|---|---|---|
| App icon | `graphics/play-icon-512.png` | 512 × 512 |
| Feature graphic | `graphics/play-feature-1024x500.png` | 1024 × 500 |
| Phone screenshots | **see the note below** | 1080 × 2400 |

**Screenshots are deliberately not included.** The obvious ones — the chat and
the conversation drawer — contained the owner's face, name, and real memory
titles. Play listings are public and permanent, so those were deleted rather
than shipped. See `SCREENSHOTS.md`.

---

## Data safety

Play asks these as a form. The answers below match what the app actually does;
they were written from the code, not from intent, and they must stay consistent
with the privacy policy at the URL above.

**Does your app collect or share any of the required user data types?** Yes.

| Data type | Collected | Shared | Purpose | Required? |
|---|---|---|---|---|
| Name | Yes | No | Account management, personalisation | Optional |
| Email address | Yes | No | Account management | Required |
| Photos | Yes | No | App functionality | Optional |
| Other user-generated content (notes) | Yes | No | App functionality | Required |
| User IDs | Yes | No | Account management | Required |

**Is all user data encrypted in transit?** Yes — HTTPS throughout; the app
refuses plain HTTP.

**Do you provide a way for users to request that their data is deleted?** Yes —
in-app, Settings → Erase everything, and Settings → Delete my account. Neither
needs a support request.

Notes on the answers, for when the reviewer asks:

- **Shared** is "No" for every row. Data is processed by the app's own backend
  and by Reeve, its memory service, acting as a processor — not sold, and not
  shared with third parties for their own purposes.
- **Photos** are optional: the app works entirely without granting photo access.
- Sign-in with Google returns the address, name, account identifier, and the
  URL of the profile photo. The photo itself is never copied to the server.

---

## Content rating questionnaire

| Question | Answer |
|---|---|
| Category | Utility, Productivity, Communication or Other |
| Violence, sexual content, profanity, drugs, gambling | No to all |
| Does the app allow users to interact or exchange content? | No — content is private to the account, with no sharing between users |
| Does the app share the user's location? | No |
| Does the app allow purchases? | No |

Expected outcome: rated for everyone / PEGI 3.

---

## App access

Play needs credentials if any part of the app is behind a login. **All of it
is.** Provide a test account in the "App access" section:

```
All functionality requires an account.
Sign in with email and password, or with Google.

Email:    <create a reviewer account and put it here>
Password: <its password>
```

Do not give the reviewer your own account: they will see your memories.

---

## Release

| Field | Value |
|---|---|
| Bundle | `bundle/app-release.aab` |
| Version name | `1.0.0` |
| Version code | `1` |
| Track | Internal testing first, then Production |

Release notes for the first version:

```
First release.

Store notes and photographs by saying them in plain words, and ask for them
back the same way. Answers show the memories they came from. Everything can be
erased from Settings at any time.
```
