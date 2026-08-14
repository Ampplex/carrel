/**
 * The terms and the privacy notice, on screen.
 *
 * A modal rather than a route because it is opened from two places that live in
 * different parts of the app — the sign-up form, which is outside the navigator
 * that Settings sits in — and a modal needs no shared navigation state to work
 * from either.
 *
 * The two documents share one sheet with a toggle. Somebody who opens the terms
 * from a consent line almost always wants a glance at the privacy notice too,
 * and closing one sheet to open another is friction for no gain.
 */

import { useEffect, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Sheet } from "../components/Sheet";
import { LEGAL_DOCS, LEGAL_VERSION, LegalDoc } from "../legal";
import { theme as t } from "../theme";

export type LegalTab = LegalDoc["key"];

export function Legal({
  open,
  onClose,
}: {
  /** Which document to show, or null for closed. */
  open: LegalTab | null;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<LegalTab>(open ?? "terms");
  const insets = useSafeAreaInsets();

  // Reopening from a different link should land on that document, not on
  // whichever one was last read.
  useEffect(() => {
    if (open) setTab(open);
  }, [open]);

  const doc = LEGAL_DOCS.find((d) => d.key === tab) ?? LEGAL_DOCS[0];

  // Level 20: this is opened from inside Settings, which is itself a sheet.
  return (
    <Sheet open={open !== null} onClose={onClose} level={20}>
      <View style={[s.screen, { paddingTop: insets.top + 8 }]}>
        <View style={s.header}>
          <Text style={s.title}>Legal</Text>
          <Pressable onPress={onClose} hitSlop={12}>
            <Text style={s.close}>Done</Text>
          </Pressable>
        </View>

        <View style={s.tabs}>
          {LEGAL_DOCS.map((d) => (
            <Pressable
              key={d.key}
              style={[s.tab, d.key === tab && s.tabOn]}
              onPress={() => setTab(d.key)}
              accessibilityRole="tab"
              accessibilityState={{ selected: d.key === tab }}
            >
              <Text style={[s.tabText, d.key === tab && s.tabTextOn]}>{d.tab}</Text>
            </Pressable>
          ))}
        </View>

        <ScrollView
          contentContainerStyle={{ paddingBottom: insets.bottom + 40 }}
          showsVerticalScrollIndicator={false}
        >
          <Text style={s.docTitle}>{doc.title}</Text>
          <Text style={s.updated}>Version {LEGAL_VERSION}</Text>
          <Text style={s.intro}>{doc.intro}</Text>

          {doc.sections.map((section) => (
            <View key={section.heading} style={s.section}>
              <Text style={s.heading}>{section.heading}</Text>
              <Text style={s.body}>{section.body}</Text>
            </View>
          ))}
        </ScrollView>
      </View>
    </Sheet>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: t.color.bg, paddingHorizontal: 20 },
  header: { flexDirection: "row", alignItems: "center", marginBottom: t.space(4) },
  title: { color: t.color.ink, ...t.text.title, flex: 1 },
  close: { color: t.color.accent, ...t.text.label },

  tabs: {
    flexDirection: "row",
    backgroundColor: t.color.card,
    borderRadius: t.radius.pill,
    padding: 4,
    marginBottom: t.space(6),
  },
  tab: {
    flex: 1,
    height: 36,
    borderRadius: t.radius.pill,
    alignItems: "center",
    justifyContent: "center",
  },
  tabOn: { backgroundColor: t.color.cardRaised },
  tabText: { color: t.color.inkTertiary, ...t.text.label },
  tabTextOn: { color: t.color.ink },

  docTitle: { color: t.color.ink, ...t.text.title, marginBottom: 4 },
  updated: {
    color: t.color.inkTertiary,
    ...t.text.small,
    marginBottom: t.space(4),
    letterSpacing: 0.4,
  },
  intro: {
    color: t.color.inkSecondary,
    ...t.text.body,
    lineHeight: 23,
    marginBottom: t.space(6),
  },

  section: { marginBottom: t.space(6) },
  heading: {
    color: t.color.ink,
    ...t.text.label,
    fontSize: 14,
    marginBottom: 6,
  },
  body: { color: t.color.inkSecondary, ...t.text.body, fontSize: 14.5, lineHeight: 22 },
});
