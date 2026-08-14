/**
 * Sign in or create an account.
 *
 * One screen that toggles, rather than two that navigate — at this size the
 * difference between the modes is a single extra field, and making people move
 * between screens to find out they were on the wrong one is a poor trade.
 *
 * The password rule is stated up front rather than after a failed submit. The
 * server enforces it either way; showing it early just avoids typing something
 * twice.
 */

import { useState } from "react";
import {
  ActivityIndicator,
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
import { theme as t } from "../theme";

export function Auth({ onSignedIn }: { onSignedIn: (s: Session) => void }) {
  const [mode, setMode] = useState<"in" | "up">("up");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
            secureTextEntry
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
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function Field({
  label,
  ...props
}: { label: string } & React.ComponentProps<typeof TextInput>) {
  const [focused, setFocused] = useState(false);
  return (
    <View>
      <Text style={s.label}>{label}</Text>
      <TextInput
        {...props}
        style={[s.input, focused && s.inputFocused]}
        placeholderTextColor={t.color.inkTertiary}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
      />
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

  switch: { alignItems: "center", marginTop: t.space(5) },
  switchText: { color: t.color.accent, ...t.text.label, fontWeight: "500" },
});
