/**
 * "Continue with Google", and the reason it is its own component.
 *
 * `useIdTokenAuthRequest` throws while rendering if the client id for the
 * current platform is missing — a red screen, not a caught error. Hooks cannot
 * be called conditionally, so a guard inside the sign-in screen could not stop
 * it: the hook ran anyway and took the whole screen down on iOS, where only a
 * Web client id was configured.
 *
 * Moving it here fixes that properly. The hook is unconditional *within this
 * component*, and the component is only mounted when `googleConfigured()` says
 * this platform has an id to use. Nothing is skipped; something is simply not
 * rendered.
 */

import { Pressable, StyleSheet, Text, View } from "react-native";
import { useGoogleSignIn } from "../googleAuth";
import { theme as t } from "../theme";

export function GoogleButton({
  disabled,
  onIdToken,
  onError,
}: {
  disabled?: boolean;
  onIdToken: (idToken: string) => void;
  onError: (message: string) => void;
}) {
  const google = useGoogleSignIn(onIdToken, onError);

  return (
    // A white button with a "G", not Google's four-colour mark. The app carries
    // no image assets and no SVG renderer, and Google's branding guidelines are
    // specific about how the real logo may be drawn — an approximation of it
    // would be worse than not using it. Swap in the official asset before this
    // goes anywhere near a store.
    <Pressable
      style={[s.button, disabled && s.off]}
      onPress={google.start}
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
