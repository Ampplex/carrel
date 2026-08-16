/**
 * Sign in or create an account.
 *
 * One screen that toggles, rather than two that navigate — at this size the
 * difference between the modes is a single extra field, and making people move
 * between screens to find out they were on the wrong one is a poor trade.
 *
 * The password rule is stated up front rather than after a failed submit. The
 * server enforces it either way; showing it early just avoids typing something
 * twice. For the same reason the password can be revealed: this account cannot
 * be recovered if the password is mistyped and forgotten, so being able to
 * check what you typed matters more here than it does in an app with a reset
 * link.
 */

import { useState } from "react";
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ApiError, Session, api } from "../api";
import { GoogleButton } from "../components/GoogleButton";
import { theme as t } from "../theme";
import { Legal, LegalTab } from "./Legal";

export function Auth({ onSignedIn }: { onSignedIn: (s: Session) => void }) {
  const [mode, setMode] = useState<"in" | "up">("up");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [legal, setLegal] = useState<LegalTab | null>(null);
  const insets = useSafeAreaInsets();

  const signingUp = mode === "up";
  const ready = email.trim().length > 3 && password.length >= (signingUp ? 8 : 1);

  const submit = async () => {
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    try {
      const session = signingUp
        ? await api.register(email.trim(), password, name.trim())
        : await api.login(email.trim(), password);
      onSignedIn(session);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  // Google returns an identity token; the server decides what it is worth.
  // Nothing here inspects it, because a client that reads its own token learns
  // nothing it can safely act on.
  const signInWithGoogle = async (idToken: string) => {
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await api.signInWithGoogle(idToken));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  /**
   * Ask for a reset link.
   *
   * The reply is the same whether or not the address has an account — the
   * server refuses to say, so the app must not imply otherwise. It reports what
   * was requested, never what was found.
   */
  const forgotPassword = async () => {
    const address = email.trim();
    if (!address) {
      setError("Type your email address first, then tap this.");
      return;
    }
    setError(null);
    try {
      const result = await api.forgotPassword(address);
      Alert.alert("Check your email", result.message);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  return (
    <KeyboardAvoidingView
      style={s.screen}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <ScrollView
        contentContainerStyle={[
          s.content,
          { paddingTop: insets.top + 40, paddingBottom: insets.bottom + 40 },
        ]}
        keyboardShouldPersistTaps="handled"
      >
        <Text style={s.brand}>Carrel</Text>
        <Text style={s.lede}>
          {signingUp
            ? "A memory for the things you'll need later."
            : "Welcome back."}
        </Text>

        <View style={s.form}>
          {signingUp && (
            <Field
              label="Name"
              value={name}
              onChangeText={setName}
              placeholder="Optional"
              autoCapitalize="words"
              textContentType="name"
            />
          )}
          <Field
            label="Email"
            value={email}
            onChangeText={setEmail}
            placeholder="you@university.edu"
            autoCapitalize="none"
            keyboardType="email-address"
            textContentType="emailAddress"
          />
          <Field
            label="Password"
            value={password}
            onChangeText={setPassword}
            placeholder={signingUp ? "At least 8 characters" : "Your password"}
            revealable
            autoCapitalize="none"
            textContentType={signingUp ? "newPassword" : "password"}
            // Submitting from the keyboard is what people expect on the last
            // field of a short form; reaching for a button below the keyboard
            // is the slower path.
            returnKeyType="go"
            onSubmitEditing={submit}
          />
        </View>

        {error && (
          <View style={s.error}>
            <Text style={s.errorText}>{error}</Text>
          </View>
        )}

        <Pressable style={[s.cta, !ready && s.ctaOff]} onPress={submit} disabled={!ready || busy}>
          {busy ? (
            <ActivityIndicator color={t.color.accentInk} />
          ) : (
            <Text style={s.ctaText}>{signingUp ? "Create account" : "Sign in"}</Text>
          )}
        </Pressable>

        <View style={s.dividerRow}>
          <View style={s.divider} />
          <Text style={s.dividerText}>or</Text>
          <View style={s.divider} />
        </View>

        <GoogleButton
          disabled={busy}
          onIdToken={signInWithGoogle}
          onError={(message) => setError(message)}
        />

        {/* Under the button, where it is read as a condition of pressing it,
            rather than in a footer nobody scrolls to. Only on sign-up: asking
            somebody to re-agree every time they sign in says nothing, and a
            consent that is collected constantly stops being read at all. */}
        {signingUp ? (
          <Text style={s.consent}>
            By creating an account you agree to the{" "}
            <Text style={s.consentLink} onPress={() => setLegal("terms")}>
              Terms of Use
            </Text>{" "}
            and the{" "}
            <Text style={s.consentLink} onPress={() => setLegal("privacy")}>
              Privacy Policy
            </Text>
            .
          </Text>
        ) : (
          <View style={s.legalRow}>
            <Pressable onPress={() => setLegal("terms")} hitSlop={10}>
              <Text style={s.legalLink}>Terms</Text>
            </Pressable>
            <Text style={s.legalDot}>·</Text>
            <Pressable onPress={() => setLegal("privacy")} hitSlop={10}>
              <Text style={s.legalLink}>Privacy</Text>
            </Pressable>
          </View>
        )}

        <Pressable
          onPress={() => {
            setMode(signingUp ? "in" : "up");
            setError(null);
          }}
          hitSlop={10}
          style={s.switch}
        >
          <Text style={s.switchText}>
            {signingUp ? "I already have an account" : "Create an account instead"}
          </Text>
        </Pressable>

        {/* Only when signing in. Offering it during sign-up would be asking to
            reset a password that does not exist yet. */}
        {!signingUp && (
          <Pressable onPress={forgotPassword} hitSlop={10} style={s.forgot}>
            <Text style={s.forgotText}>Forgot password?</Text>
          </Pressable>
        )}
      </ScrollView>

      <Legal open={legal} onClose={() => setLegal(null)} />
    </KeyboardAvoidingView>
  );
}

function Field({
  label,
  revealable,
  ...props
}: {
  label: string;
  /** Renders as a password with a show/hide control. */
  revealable?: boolean;
} & React.ComponentProps<typeof TextInput>) {
  const [focused, setFocused] = useState(false);
  const [shown, setShown] = useState(false);

  return (
    <View>
      <Text style={s.label}>{label}</Text>
      <View>
        <TextInput
          {...props}
          secureTextEntry={revealable ? !shown : props.secureTextEntry}
          style={[s.input, focused && s.inputFocused, revealable && s.inputWithButton]}
          placeholderTextColor={t.color.inkTertiary}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
        />
        {revealable && (
          <Pressable
            style={s.reveal}
            onPress={() => setShown((v) => !v)}
            // The button sits inside a 50pt-tall field, so it cannot be a full
            // 44pt square without crowding the text; the slop makes up the
            // difference in every direction.
            hitSlop={8}
            accessibilityRole="button"
            accessibilityLabel={shown ? "Hide password" : "Show password"}
          >
            {/* Full-strength ink, not the tertiary grey used for hints: at a
                1.5pt stroke a dim colour disappears into the field it sits in.
                Revealed state goes accent, which is both brighter still and
                the palette's one signal for "this is doing something". */}
            <Eye crossed={shown} color={shown ? t.color.accent : t.color.ink} />
          </Pressable>
        )}
      </View>
    </View>
  );
}

/**
 * An eye, drawn from two arcs.
 *
 * The app carries no icon font — the hamburger in Chat is three plain Views for
 * the same reason — and a whole vector library for one glyph is not a trade
 * worth making.
 *
 * The obvious construction, a square with two opposite corners rounded and
 * turned forty-five degrees, comes out chopped: the radius is clamped to half
 * the side, so half of each edge stays a straight line and the "eye" has flat
 * sides. This draws the real thing instead. Each lid is a shallow slice of a
 * large circle, taken by clipping a 25pt ring down to a 6.5pt window — top
 * slice and bottom slice, stacked. Slicing a big circle shallowly is what makes
 * the curve gentle; the whole shape's proportions then come from arithmetic
 * rather than from squashing something that was the wrong shape to begin with.
 *
 * The slash means "this will hide it", so the icon describes what the button
 * does rather than what the field is currently doing. Either convention is
 * defensible; the accessibility label removes the ambiguity for anyone who
 * cannot see the difference.
 */
function Eye({ crossed, color }: { crossed: boolean; color: string }) {
  return (
    <View style={s.eye}>
      <View style={s.eyeShape}>
        <View style={s.eyeLidTop}>
          <View style={[s.eyeRing, { borderColor: color }]} />
        </View>
        <View style={s.eyeLidBottom}>
          <View style={[s.eyeRing, { borderColor: color }]} />
        </View>
      </View>
      <View style={[s.eyePupil, { borderColor: color }]} />
      {crossed && <View style={[s.eyeSlash, { backgroundColor: color }]} />}
    </View>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: t.color.bg },
  content: { flexGrow: 1, justifyContent: "center", paddingHorizontal: 28 },

  brand: { color: t.color.ink, ...t.text.display, marginBottom: t.space(2) },
  lede: { color: t.color.inkSecondary, ...t.text.body, marginBottom: t.space(9) },

  form: { gap: t.space(4) },
  label: {
    color: t.color.inkTertiary,
    ...t.text.small,
    marginBottom: 6,
    textTransform: "uppercase",
    letterSpacing: 0.8,
  },
  input: {
    height: 50,
    borderRadius: t.radius.md,
    backgroundColor: t.color.card,
    borderWidth: 1,
    borderColor: t.color.border,
    paddingHorizontal: 16,
    color: t.color.ink,
    fontSize: 16,
  },
  inputFocused: { borderColor: t.color.accent },
  // Room for the reveal button, so a long password does not run underneath it.
  inputWithButton: { paddingRight: 52 },

  reveal: {
    position: "absolute",
    right: 3,
    top: 0,
    bottom: 0,
    width: 46,
    alignItems: "center",
    justifyContent: "center",
  },

  // A 25pt ring sliced twice. At a window depth of 6.5 the visible chord is
  // 21.9 wide — just inside the 22pt clip, so the arc ends at the eye's corner
  // rather than being cut short of it.
  eye: { width: 26, height: 26, alignItems: "center", justifyContent: "center" },
  eyeShape: { width: 22, height: 13 },
  eyeLidTop: {
    width: 22,
    height: 6.5,
    overflow: "hidden",
    alignItems: "center",
    justifyContent: "flex-start", // keeps the top of the ring in the window
  },
  eyeLidBottom: {
    width: 22,
    height: 6.5,
    overflow: "hidden",
    alignItems: "center",
    justifyContent: "flex-end", // and the bottom of it in this one
  },
  eyeRing: { width: 25, height: 25, borderRadius: 12.5, borderWidth: 1.5 },

  // Placed with explicit offsets rather than relying on the parent's centring,
  // which absolute children follow only when no inset is given.
  eyePupil: {
    position: "absolute",
    left: 9.5,
    top: 9.5,
    width: 7,
    height: 7,
    borderRadius: 3.5,
    borderWidth: 1.5,
  },
  eyeSlash: {
    position: "absolute",
    left: 0,
    top: 12.25,
    width: 26,
    height: 1.5,
    borderRadius: 1,
    transform: [{ rotate: "45deg" }],
  },

  error: {
    marginTop: t.space(4),
    padding: 12,
    borderRadius: t.radius.sm,
    backgroundColor: t.color.dangerSoft,
    borderWidth: 1,
    borderColor: t.color.danger,
  },
  errorText: { color: t.color.danger, ...t.text.small, fontSize: 13 },

  cta: {
    height: 52,
    borderRadius: t.radius.pill,
    backgroundColor: t.color.accent,
    alignItems: "center",
    justifyContent: "center",
    marginTop: t.space(7),
  },
  ctaOff: { opacity: 0.35 },
  ctaText: { color: t.color.accentInk, fontSize: 16, fontWeight: "700" },

  dividerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    marginTop: t.space(5),
    marginBottom: t.space(4),
  },
  divider: { flex: 1, height: StyleSheet.hairlineWidth, backgroundColor: t.color.border },
  dividerText: { color: t.color.inkTertiary, ...t.text.small },

  consent: {
    color: t.color.inkTertiary,
    ...t.text.small,
    lineHeight: 18,
    textAlign: "center",
    marginTop: t.space(4),
    paddingHorizontal: 8,
  },
  consentLink: { color: t.color.accent, fontWeight: "600" },

  // Deliberately quieter than the consent line: on sign-in these are reference
  // material, and two accent-coloured rows stacked above the mode switch would
  // read as three competing calls to action.
  legalRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    marginTop: t.space(4),
  },
  legalLink: { color: t.color.inkTertiary, ...t.text.small },
  legalDot: { color: t.color.inkTertiary, ...t.text.small },

  switch: { alignItems: "center", marginTop: t.space(5) },
  forgot: { alignItems: "center", paddingVertical: 12 },
  forgotText: { color: t.color.inkTertiary, ...t.text.small },
  switchText: { color: t.color.accent, ...t.text.label, fontWeight: "500" },
});
