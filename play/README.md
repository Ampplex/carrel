# Carrel — Play Console upload pack

Built from commit `HEAD` on the day it was generated. Everything Play asks for
is here except screenshots; `SCREENSHOTS.md` explains why and how to make them.

```
bundle/app-release.aab          the upload  ·  51 MB  ·  versionCode 1  ·  1.0.0
graphics/play-icon-512.png      store icon  ·  512 × 512
graphics/play-feature-1024x500.png          feature graphic
LISTING.md                      every text field, ready to paste
SCREENSHOTS.md                  what is missing and why
```

## Order of operations in the console

1. **Create the app** — name `Carrel`, English (UK), App, Free.
2. **App access** — every screen needs an account, so Play requires credentials.
   Make a reviewer account first; do not give them yours.
3. **Data safety** — the answers in `LISTING.md` were written from the code and
   must stay consistent with the privacy policy, which Google fetches.
4. **Content rating** — the questionnaire answers are in `LISTING.md`.
5. **Store listing** — short description, full description, icon, feature
   graphic, screenshots.
6. **Internal testing → create release** — upload the `.aab`, paste the release
   notes, roll out to yourself first.
7. **Production** only once internal testing has installed and run.

## Signing — read this before uploading

The bundle is signed with the key in `~/CarrelSigning/carrel-release.keystore`:

```
SHA-1  A8:49:F2:B9:8E:5B:F7:76:AA:CC:68:6F:16:82:41:23:4F:60:3B:53
```

When you enrol in **Play App Signing** — which Play will offer, and which you
should accept — Google keeps the real signing key and this one becomes the
**upload key**. That is a meaningful improvement: losing an upload key is
recoverable through support, whereas losing the app signing key is not.

It also means the app's final signature is **Google's, not this one**. If you
ever move to the native Google Sign-In SDK, the certificate fingerprint to
register would be the one Play shows under *Setup → App signing*, not the one
above. The current browser-based OAuth flow does not check fingerprints at all,
so nothing needs changing today.

## What will get this rejected

- **Screenshots showing someone's real data.** The first pair did; they were
  deleted. See `SCREENSHOTS.md`.
- **A data safety form that contradicts the privacy policy.** Google reads both.
  The app collects email, name, notes and photographs, and the form says so.
- **A reviewer account that does not work.** Test it in a fresh install before
  submitting; the whole app is behind a login and a reviewer who cannot get in
  will reject rather than ask.
