/**
 * Whether the intro has been shown.
 *
 * Its own module because App.tsx and OnboardingScreen both need it, and having
 * the screen import it from App.tsx created a require cycle
 * (App → OnboardingScreen → App). Metro allows cycles but resolves them by
 * handing back whatever is initialised at the time — so `markIntroSeen` could
 * legitimately arrive as `undefined` and the intro would replay forever.
 */

import * as SecureStore from "expo-secure-store";

const SEEN_INTRO = "carrel.seen.intro";

export async function hasSeenIntro(): Promise<boolean> {
  try {
    return (await SecureStore.getItemAsync(SEEN_INTRO)) === "1";
  } catch {
    // Keychain unavailable: showing the intro again is a far smaller failure
    // than blocking someone at a screen they cannot get past.
    return false;
  }
}

export async function markIntroSeen(): Promise<void> {
  try {
    await SecureStore.setItemAsync(SEEN_INTRO, "1");
  } catch {
    /* the intro will simply appear once more */
  }
}
