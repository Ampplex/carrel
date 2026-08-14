/**
 * "Continue with Google", and the reason it is split in two.
 *
 * `useIdTokenAuthRequest` throws while rendering if the client id for the
 * current platform is missing — a red screen, not a caught error. Hooks cannot
 * be called conditionally, so a guard inside the sign-in screen could not stop
 * it: the hook ran anyway and took the whole screen down on iOS, where only a
 * Web client id was configured.
 *
 * Hence the split. `Shell` is the button and knows nothing; `Live` adds the
 * hook and is only ever mounted when this platform has an id for it to use.
 * Nothing is skipped conditionally — one component is simply not rendered.
 *
 * The button itself is always visible, including before any client id exists.
 * The first version hid it, which is defensible for a shipped app and useless
 * here: an invisible button looks identical to a broken build, and the honest
 * answer — "this needs an iOS client id and a development build" — is worth
 * saying out loud rather than expressing as an absence.
 */

import { Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { googleConfigured, useGoogleSignIn } from "../googleAuth";
import { theme as t } from "../theme";

/** What is missing, in the words of somebody who has to go and fix it. */
function whatIsMissing(): string {
  const platform = Platform.OS === "android" ? "an Android" : "an iOS";
  return (
    `Google sign-in needs ${platform} client ID. Create one in the Google Cloud ` +
    "console, add it to mobile/src/googleAuth.ts and to GOOGLE_CLIENT_IDS in " +
    "backend/.env, then run a development build — Expo Go cannot complete " +
    "Google's redirect."
  );
}

export function GoogleButton({
  disabled,
  onIdToken,
  onError,
}: {
  disabled?: boolean;
  onIdToken: (idToken: string) => void;
  onError: (message: string) => void;
}) {
  if (!googleConfigured()) {
    return <Shell disabled={disabled} onPress={() => onError(whatIsMissing())} />;
  }
  return <Live disabled={disabled} onIdToken={onIdToken} onError={onError} />;
}

function Live({
  disabled,
  onIdToken,
  onError,
}: {
  disabled?: boolean;
  onIdToken: (idToken: string) => void;
  onError: (message: string) => void;
}) {
  const google = useGoogleSignIn(onIdToken, onError);
  return <Shell disabled={disabled} onPress={google.start} />;
}

function Shell({ disabled, onPress }: { disabled?: boolean; onPress: () => void }) {
  return (
    // A white button with a "G", not Google's four-colour mark. The app carries
    // no image assets and no SVG renderer, and Google's branding guidelines are
    // specific about how the real logo may be drawn — an approximation of it
    // would be worse than not using it. Swap in the official asset before this
    // goes anywhere near a store.
    <Pressable
      style={[s.button, disabled && s.off]}
      onPress={onPress}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel="Continue with Google"
    >
      <View style={s.mark}>
        <Text style={s.markText}>G</Text>
      </View>
      <Text style={s.label}>Continue with Google</Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  button: {
    height: 52,
    borderRadius: t.radius.pill,
    // White, because it is the one background Google's mark is guaranteed to be
    // legible on, and because a dark app still has to render this button the
    // way people recognise it.
    backgroundColor: "#FFFFFF",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
  },
  off: { opacity: 0.35 },
  mark: { width: 22, height: 22, alignItems: "center", justifyContent: "center" },
  markText: { color: "#4285F4", fontSize: 19, fontWeight: "700" },
  label: { color: "#1F1F1F", fontSize: 16, fontWeight: "600" },
});
