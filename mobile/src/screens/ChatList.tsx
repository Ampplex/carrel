/**
 * The list of conversations, as a draggable left drawer.
 *
 * A drawer over a dimmed chat, which is the shape people already know from
 * every assistant app. Deliberately not full-screen: keeping the conversation
 * visible behind it makes switching feel like moving between threads rather
 * than navigating away and coming back.
 *
 * The motion is hand-rolled on `Animated` + `PanResponder` rather than pulled
 * in from a drawer library. Reanimated is not installed and a navigation drawer
 * would restructure the whole app for one panel; this is about forty lines and
 * uses the native driver, so it runs on the UI thread rather than in JS.
 *
 * Dragging matters more than it sounds. A drawer that only responds to taps
 * feels like a modal wearing a costume — the thing that makes it read as a
 * drawer is that it tracks your finger and can be thrown shut.
 *
 * The line at the bottom is not decoration. Deleting a conversation removes the
 * transcript and nothing else — every fact in it stays answerable from any
 * other chat, because sessions organise conversations and do not partition
 * memory. Without saying so, "delete" reads as erasure, and someone will one
 * day delete a chat expecting to forget what they said in it.
 */

import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Animated,
  Dimensions,
  FlatList,
  Modal,
  PanResponder,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ApiError, ChatSummary, api } from "../api";
import { theme as t } from "../theme";

/** Leaves a strip of the conversation showing behind the panel. */
const WIDTH = Math.min(Dimensions.get("window").width * 0.86, 360);

/** Past this much of the panel dragged away, release closes it. */
const CLOSE_FRACTION = 0.4;
/** A fast flick closes regardless of how far it travelled. */
const FLICK_VELOCITY = 0.5;

export function ChatList({
  visible,
  currentId,
  onPick,
  onClose,
  onSettings,
}: {
  visible: boolean;
  currentId: string | null;
  onPick: (id: string) => void;
  onClose: () => void;
  onSettings: () => void;
}) {
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const insets = useSafeAreaInsets();

  // Kept mounted through the closing animation — unmounting on `visible`
  // alone would make the panel vanish instead of sliding out.
  const [mounted, setMounted] = useState(visible);
  const slide = useRef(new Animated.Value(-WIDTH)).current;

  const animateTo = (to: number, done?: () => void) =>
    Animated.spring(slide, {
      toValue: to,
      useNativeDriver: true,
      bounciness: 0,
      speed: 14,
    }).start(({ finished }) => finished && done?.());

  useEffect(() => {
    if (visible) {
      setMounted(true);
      slide.setValue(-WIDTH);
      animateTo(0);
      load();
    } else if (mounted) {
      animateTo(-WIDTH, () => setMounted(false));
    }
  }, [visible]);

  const close = () => animateTo(-WIDTH, () => { setMounted(false); onClose(); });

  const pan = useRef(
    PanResponder.create({
      // Capture, not the plain variant: the conversation FlatList is a child,
      // and a scroll view claims the touch before a parent PanResponder is ever
      // asked. Capturing runs first, so a clearly horizontal drag becomes a
      // drawer gesture while vertical movement still scrolls the list.
      onMoveShouldSetPanResponderCapture: (_, g) =>
        Math.abs(g.dx) > 8 && Math.abs(g.dx) > Math.abs(g.dy) * 1.5,
      onPanResponderTerminationRequest: () => false,
      onPanResponderMove: (_, g) => {
        // Only ever drags shut; pulling right past open does nothing.
        if (g.dx < 0) slide.setValue(Math.max(-WIDTH, g.dx));
      },
      onPanResponderRelease: (_, g) => {
        const draggedFarEnough = g.dx < -WIDTH * CLOSE_FRACTION;
        const flicked = g.vx < -FLICK_VELOCITY;
        if (draggedFarEnough || flicked) {
          animateTo(-WIDTH, () => {
            setMounted(false);
            onClose();
          });
        } else {
          animateTo(0);
        }
      },
    })
  ).current;

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setChats(await api.chats());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const startNew = async () => {
    try {
      const chat = await api.createChat();
      onPick(chat.id);
      close();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  };

  const confirmDelete = (chat: ChatSummary) => {
    Alert.alert(
      "Delete this conversation?",
      "The messages go. Anything you told Carrel in it stays remembered, and can still be asked about from any chat.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            try {
              await api.deleteChat(chat.id);
              if (chat.id === currentId) {
                const fresh = await api.createChat();
                onPick(fresh.id);
              }
              load();
            } catch (e) {
              setError(e instanceof ApiError ? e.message : String(e));
            }
          },
        },
      ]
    );
  };

  // The chat behind dims in step with the panel, so the drag feels connected to
  // something rather than sliding over a static backdrop.
  const scrimOpacity = slide.interpolate({
    inputRange: [-WIDTH, 0],
    outputRange: [0, 1],
    extrapolate: "clamp",
  });

  if (!mounted) return null;

  return (
    <Modal visible transparent animationType="none" onRequestClose={close}>
      <Animated.View style={[s.scrim, { opacity: scrimOpacity }]}>
        <Pressable style={s.fill} onPress={close} />
      </Animated.View>

      <Animated.View
        style={[
          s.panel,
          { width: WIDTH, paddingTop: insets.top + 8, transform: [{ translateX: slide }] },
        ]}
        {...pan.panHandlers}
      >
        <View style={s.header}>
          <Text style={s.title}>Conversations</Text>
        </View>

        <Pressable style={s.newBtn} onPress={startNew}>
          <Text style={s.newBtnText}>+  New conversation</Text>
        </Pressable>

        {error && <Text style={s.error}>{error}</Text>}

        {loading ? (
          <ActivityIndicator color={t.color.accent} style={{ marginTop: 32 }} />
        ) : (
          <FlatList
            data={chats}
            keyExtractor={(c) => c.id}
            contentContainerStyle={{ paddingBottom: 16 }}
            ListEmptyComponent={<Text style={s.empty}>No conversations yet.</Text>}
            renderItem={({ item }) => (
              <Pressable
                style={[s.row, item.id === currentId && s.rowCurrent]}
                onPress={() => {
                  onPick(item.id);
                  close();
                }}
                onLongPress={() => confirmDelete(item)}
              >
                <View style={s.fill}>
                  <Text style={s.rowTitle} numberOfLines={1}>
                    {item.title}
                  </Text>
                  {!!item.preview && (
                    <Text style={s.rowPreview} numberOfLines={1}>
                      {item.preview}
                    </Text>
                  )}
                </View>
                <Text style={s.count}>{item.message_count}</Text>
              </Pressable>
            )}
          />
        )}

        <Pressable
          style={s.settingsRow}
          onPress={() => {
            // Announce the intent and close. Opening Settings on a timer from
            // here raced the drawer's own dismissal — see components/Sheet for
            // what that cost. The parent now opens it when this modal is
            // genuinely gone, which is a fact rather than an estimate.
            onSettings();
            close();
          }}
        >
          <Text style={s.settingsText}>Settings</Text>
        </Pressable>

        <Text style={[s.footnote, { marginBottom: insets.bottom + 8 }]}>
          Conversations only organise what you see. Everything you tell Carrel is
          remembered across all of them.
        </Text>
      </Animated.View>
    </Modal>
  );
}

const s = StyleSheet.create({
  fill: { flex: 1 },
  scrim: {
    position: "absolute",
    left: 0,
    right: 0,
    top: 0,
    bottom: 0,
    backgroundColor: "rgba(0,0,0,0.55)",
  },
  panel: {
    position: "absolute",
    left: 0,
    top: 0,
    bottom: 0,
    backgroundColor: t.color.card,
    paddingHorizontal: 18,
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: t.color.borderStrong,
  },

  header: { flexDirection: "row", alignItems: "center", marginBottom: t.space(5) },
  title: { color: t.color.ink, ...t.text.title, flex: 1 },

  newBtn: {
    borderWidth: 1,
    borderColor: t.color.borderStrong,
    borderRadius: t.radius.md,
    paddingVertical: 13,
    alignItems: "center",
    marginBottom: t.space(5),
  },
  newBtnText: { color: t.color.ink, ...t.text.label },

  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderRadius: t.radius.md,
    marginBottom: 4,
    backgroundColor: t.color.cardRaised,
    borderWidth: 1,
    borderColor: "transparent",
  },
  rowCurrent: { borderColor: t.color.accent },
  rowTitle: { color: t.color.ink, ...t.text.body, fontSize: 15 },
  rowPreview: { color: t.color.inkTertiary, ...t.text.small, marginTop: 2 },
  count: { color: t.color.inkTertiary, ...t.text.mono },

  settingsRow: {
    paddingVertical: 13,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: t.color.border,
    marginTop: 6,
  },
  settingsText: { color: t.color.ink, ...t.text.label },
  empty: { color: t.color.inkTertiary, ...t.text.small, textAlign: "center", marginTop: 40 },
  error: { color: t.color.danger, ...t.text.small, marginBottom: 12 },
  footnote: {
    color: t.color.inkTertiary,
    ...t.text.small,
    fontSize: 11.5,
    textAlign: "center",
    lineHeight: 16,
    marginTop: 12,
  },
});
