/**
 * Settings — mostly a place to leave.
 *
 * There is very little to configure in Carrel, and inventing options to fill a
 * screen would be worse than a short one. What does belong here is the ability
 * to take your data back, which is not a setting so much as an obligation.
 *
 * The two destructive actions are kept apart on purpose. "Erase everything"
 * empties the app and leaves you signed in; "Delete account" takes the login
 * too. Collapsing them into one button would mean somebody who wanted a clean
 * slate loses their account, or somebody leaving finds their memories still on
 * a server.
 *
 * Both require typing a phrase rather than tapping a red button. A button can
 * be hit by accident on a phone in a pocket; a phrase cannot.
 */

import { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ApiError, Session, api } from "../api";
import { Sheet } from "../components/Sheet";
import { LEGAL_VERSION } from "../legal";
import { theme as t } from "../theme";
import { Legal, LegalTab } from "./Legal";

const PHRASE = "DELETE MY MEMORY";

export function Settings({
  visible,
  session,
  onClose,
  onSignedOut,
}: {
  visible: boolean;
  session: Session;
  onClose: () => void;
  onSignedOut: () => void;
}) {
  const [mode, setMode] = useState<null | "erase" | "delete">(null);
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [legal, setLegal] = useState<LegalTab | null>(null);
  const insets = useSafeAreaInsets();

  const reset = () => {
    setMode(null);
    setConfirm("");
    setError(null);
  };

  const run = async () => {
    if (confirm.trim() !== PHRASE || busy) return;
    setBusy(true);
    setError(null);
    try {
      const result =
        mode === "delete"
          ? await api.deleteAccount(confirm.trim())
          : await api.eraseData(confirm.trim());

      const d = result.deleted;
      setDone(
        `Gone: ${d.memories} memories, ${d.local_photos} photos, ` +
          `${d.conversations} conversations.`
      );
      reset();

      // Deleting the account invalidates the token, so there is nothing left to
      // stay signed in to.
      if (mode === "delete") setTimeout(onSignedOut, 1600);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet open={visible} onClose={onClose}>
      <View style={[s.screen, { paddingTop: insets.top + 8 }]}>
        <View style={s.header}>
          <Text style={s.title}>Settings</Text>
          <Pressable onPress={() => { reset(); onClose(); }} hitSlop={12}>
            <Text style={s.close}>Done</Text>
          </Pressable>
        </View>

        <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + 32 }}>
          <Text style={s.sectionLabel}>Signed in as</Text>
          <View style={s.card}>
            <Text style={s.value}>{session.email}</Text>
            {!!session.name && <Text style={s.sub}>{session.name}</Text>}
          </View>

          <Pressable style={s.card} onPress={onSignedOut}>
            <Text style={s.action}>Sign out</Text>
          </Pressable>

          {done && (
            <View style={s.doneBox}>
              <Text style={s.doneText}>{done}</Text>
            </View>
          )}

          {/* Above the danger zone rather than below it: the privacy notice is
              what explains where the data being erased actually lives, and
              burying it under the destructive buttons puts it after the point
              where somebody needed it. */}
          <Text style={s.sectionLabel}>About</Text>
          <Pressable style={s.card} onPress={() => setLegal("terms")}>
            <Text style={s.action}>Terms of Use</Text>
          </Pressable>
          <Pressable style={s.card} onPress={() => setLegal("privacy")}>
            <Text style={s.action}>Privacy Policy</Text>
            <Text style={s.sub}>What is stored, where it goes, and how to get rid of it.</Text>
          </Pressable>
          <Text style={s.version}>Agreements version {LEGAL_VERSION}</Text>

          <Text style={s.sectionLabel}>Your data</Text>
          <Text style={s.explain}>
            Everything you have told Carrel lives under your account and nobody
            else's. Erasing removes the memories, the photographs it kept, and
            every conversation — on Carrel and on Reeve, straight away, with no
            grace period and no copy retained.
          </Text>

          {mode === null ? (
            <>
              <Pressable style={s.card} onPress={() => setMode("erase")}>
                <Text style={s.danger}>Erase everything</Text>
                <Text style={s.sub}>Empties the app. You stay signed in.</Text>
              </Pressable>

              <Pressable style={s.card} onPress={() => setMode("delete")}>
                <Text style={s.danger}>Delete my account</Text>
                <Text style={s.sub}>Erases everything, then removes the login itself.</Text>
              </Pressable>
            </>
          ) : (
            <View style={s.confirmBox}>
              <Text style={s.confirmTitle}>
                {mode === "delete" ? "Delete your account?" : "Erase everything?"}
              </Text>
              <Text style={s.sub}>
                This cannot be undone. Type{" "}
                <Text style={s.phrase}>{PHRASE}</Text> to confirm.
              </Text>
              <TextInput
                style={s.input}
                value={confirm}
                onChangeText={setConfirm}
                placeholder={PHRASE}
                placeholderTextColor={t.color.inkTertiary}
                autoCapitalize="characters"
                autoCorrect={false}
              />
              {error && <Text style={s.error}>{error}</Text>}
              <View style={s.row}>
                <Pressable style={s.cancel} onPress={reset}>
                  <Text style={s.cancelText}>Cancel</Text>
                </Pressable>
                <Pressable
                  style={[s.confirmBtn, confirm.trim() !== PHRASE && s.confirmOff]}
                  onPress={run}
                  disabled={confirm.trim() !== PHRASE || busy}
                >
                  {busy ? (
                    <ActivityIndicator color="#fff" size="small" />
                  ) : (
                    <Text style={s.confirmText}>
                      {mode === "delete" ? "Delete account" : "Erase"}
                    </Text>
                  )}
                </Pressable>
              </View>
            </View>
          )}
        </ScrollView>

        <Legal open={legal} onClose={() => setLegal(null)} />
      </View>
    </Sheet>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: t.color.bg, paddingHorizontal: 20 },
  header: { flexDirection: "row", alignItems: "center", marginBottom: t.space(6) },
  title: { color: t.color.ink, ...t.text.title, flex: 1 },
  close: { color: t.color.accent, ...t.text.label },

  sectionLabel: {
    color: t.color.inkTertiary,
    ...t.text.small,
    textTransform: "uppercase",
    letterSpacing: 0.8,
    marginBottom: 8,
    marginTop: t.space(5),
  },
  explain: {
    color: t.color.inkSecondary,
    ...t.text.small,
    lineHeight: 19,
    marginBottom: t.space(4),
  },

  card: {
    backgroundColor: t.color.card,
    borderRadius: t.radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: t.color.border,
    padding: 15,
    marginBottom: 10,
  },
  value: { color: t.color.ink, ...t.text.body },
  sub: { color: t.color.inkTertiary, ...t.text.small, marginTop: 3, lineHeight: 17 },
  action: { color: t.color.ink, ...t.text.body },
  danger: { color: t.color.danger, ...t.text.body },
  version: { color: t.color.inkTertiary, ...t.text.small, marginTop: 2, marginLeft: 2 },

  confirmBox: {
    backgroundColor: t.color.dangerSoft,
    borderRadius: t.radius.md,
    borderWidth: 1,
    borderColor: t.color.danger,
    padding: 16,
  },
  confirmTitle: { color: t.color.ink, ...t.text.body, fontWeight: "600", marginBottom: 4 },
  phrase: { color: t.color.danger, fontWeight: "700" },
  input: {
    marginTop: 12,
    height: 46,
    borderRadius: t.radius.sm,
    backgroundColor: t.color.bg,
    borderWidth: 1,
    borderColor: t.color.borderStrong,
    paddingHorizontal: 14,
    color: t.color.ink,
    fontSize: 15,
  },
  row: { flexDirection: "row", gap: 10, marginTop: 14 },
  cancel: {
    flex: 1,
    height: 44,
    borderRadius: t.radius.pill,
    borderWidth: 1,
    borderColor: t.color.borderStrong,
    alignItems: "center",
    justifyContent: "center",
  },
  cancelText: { color: t.color.ink, ...t.text.label },
  confirmBtn: {
    flex: 1,
    height: 44,
    borderRadius: t.radius.pill,
    backgroundColor: t.color.danger,
    alignItems: "center",
    justifyContent: "center",
  },
  confirmOff: { opacity: 0.4 },
  confirmText: { color: "#2A1512", ...t.text.label, fontWeight: "700" },

  error: { color: t.color.danger, ...t.text.small, marginTop: 10 },
  doneBox: {
    backgroundColor: t.color.successSoft,
    borderRadius: t.radius.md,
    borderWidth: 1,
    borderColor: t.color.success,
    padding: 14,
    marginTop: 10,
  },
  doneText: { color: t.color.success, ...t.text.small, lineHeight: 18 },
});
