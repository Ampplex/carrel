/**
 * Three cards, then out of the way.
 *
 * Onboarding earns its place only if it changes how the first session goes, so
 * each card teaches one thing the app would otherwise be judged wrongly for:
 * that you type plainly rather than filling forms, that correcting something
 * means restating it (there is no edit button, and that is a feature), and that
 * photographs are readable later. Everything else can be discovered.
 */

import { useRef, useState } from "react";
import {
  Dimensions,
  NativeScrollEvent,
  NativeSyntheticEvent,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { theme as t } from "../theme";

const { width } = Dimensions.get("window");

const CARDS = [
  {
    glyph: "❝",
    title: "Just say it",
    body:
      "Type what happened the way you'd say it out loud. A deadline, a decision, who is doing what. No forms, no folders, no tags to maintain.",
  },
  {
    glyph: "⤳",
    title: "Corrections are memories too",
    body:
      "When something changes, say the new version. Carrel keeps both and knows which came later — so \"when is it due?\" and \"when was it originally due?\" both have answers. There's no edit button on purpose.",
  },
  {
    glyph: "◐",
    title: "Photograph anything",
    body:
      "A whiteboard, a slide, a receipt, a room. The picture is kept, not just your caption — so months later you can ask about a detail nobody thought to write down.",
  },
];

export function Onboarding({ onDone }: { onDone: () => void }) {
  const [page, setPage] = useState(0);
  const scroller = useRef<ScrollView>(null);
  const insets = useSafeAreaInsets();
  const last = page === CARDS.length - 1;

  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const next = Math.round(e.nativeEvent.contentOffset.x / width);
    if (next !== page) setPage(next);
  };

  const advance = () => {
    if (last) return onDone();
    scroller.current?.scrollTo({ x: (page + 1) * width, animated: true });
  };

  return (
    <View style={s.screen}>
      <View style={[s.skipRow, { paddingTop: insets.top }]}>
        {!last && (
          <Pressable onPress={onDone} hitSlop={12}>
            <Text style={s.skip}>Skip</Text>
          </Pressable>
        )}
      </View>

      <ScrollView
        ref={scroller}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onScroll={onScroll}
        scrollEventThrottle={16}
        style={s.flex}
      >
        {CARDS.map((c) => (
          <View key={c.title} style={[s.card, { width }]}>
            <View style={s.glyphWrap}>
              <Text style={s.glyph}>{c.glyph}</Text>
            </View>
            <Text style={s.title}>{c.title}</Text>
            <Text style={s.body}>{c.body}</Text>
          </View>
        ))}
      </ScrollView>

      <View style={[s.footer, { paddingBottom: Math.max(insets.bottom, 16) + 16 }]}>
        <View style={s.dots}>
          {CARDS.map((c, i) => (
            <View key={c.title} style={[s.dot, i === page && s.dotOn]} />
          ))}
        </View>
        <Pressable style={s.cta} onPress={advance}>
          <Text style={s.ctaText}>{last ? "Get started" : "Next"}</Text>
        </Pressable>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: t.color.bg },
  flex: { flex: 1 },
  skipRow: { minHeight: 44, justifyContent: "center", alignItems: "flex-end", paddingHorizontal: 20 },
  skip: { color: t.color.inkTertiary, ...t.text.label },

  card: { paddingHorizontal: 32, justifyContent: "center", flex: 1 },
  glyphWrap: {
    width: 76,
    height: 76,
    borderRadius: t.radius.lg,
    backgroundColor: t.color.accentSoft,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: t.space(8),
  },
  glyph: { fontSize: 34, color: t.color.accent },
  title: { color: t.color.ink, ...t.text.display, marginBottom: t.space(3) },
  body: { color: t.color.inkSecondary, ...t.text.body, fontSize: 16, lineHeight: 25 },

  footer: { paddingHorizontal: 32, gap: t.space(6) },
  dots: { flexDirection: "row", gap: 6 },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: t.color.borderStrong,
  },
  dotOn: { backgroundColor: t.color.accent, width: 20 },

  cta: {
    height: 52,
    borderRadius: t.radius.pill,
    backgroundColor: t.color.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  ctaText: { color: t.color.accentInk, fontSize: 16, fontWeight: "700" },
});
