/**
 * The whole product, on one screen.
 *
 * You say things and you ask things, and the app decides which you meant rather
 * than making you pick a mode. A question gets answered; anything else gets
 * remembered. The reply always states which happened, so a wrong guess is
 * visible immediately instead of quietly swallowing something you meant to keep.
 *
 * Attaching a photo follows the same rule: a caption stores it, a question asks
 * about it.
 *
 * What is deliberately absent: edit, delete, folders, tags, search. Restating a
 * fact IS the correction — the memory keeps both and knows which came later,
 * which is the entire reason this exists rather than a notes file.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Animated,
  Easing,
  FlatList,
  Image,
  Keyboard,
  KeyboardAvoidingView,
  PanResponder,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import * as ImagePicker from "expo-image-picker";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  API_BASE,
  ApiError,
  ParsedContext,
  PickedImage,
  Session,
  StoredMessage,
  api,
} from "../api";
import { AuthImage } from "../components/AuthImage";
import { RichText } from "../components/RichText";
import { ChatList } from "./ChatList";
import { Settings } from "./Settings";
import { theme as t } from "../theme";

type Role = "you" | "Carrel" | "note";

interface Message {
  id: string;
  role: Role;
  text: string;
  image?: PickedImage;
  question?: string;
  evidence?: ParsedContext;
  meta?: string;
  /** True while tokens are still arriving, so the bubble can show a caret. */
  streaming?: boolean;
  /** Set on a 'Remembered.' note so the user can re-run it as a question. */
  askInstead?: string;
}

/** Interrogatives — the obvious half. */
const QUESTION_WORDS =
  /^(who|what|whats|when|where|why|how|which|whose|did|do|does|is|are|was|were|can|could|should|would|will|have|has|had)\b/i;

/**
 * Imperatives — the half that was missing, and it cost more than it looks.
 *
 * "Describe the aeroplane" is a request, not a fact, but it carries no question
 * mark and opens with a verb. The first version stored it and replied
 * "Remembered." That fails twice: the question goes unanswered, AND a sentence
 * the user never meant to keep is now in their memory, competing with real
 * facts in every future retrieval.
 *
 * So asking is the safer default wherever it is ambiguous. An unnecessary
 * answer costs one query; a wrongly stored question pollutes the store for good.
 */
const REQUEST_VERBS =
  /^(describe|explain|summari[sz]e|list|find|show|tell|remind|give me|help me|compare|recall|search|look up)\b/i;

/** A question gets answered; anything else gets remembered. */
function isQuestion(text: string): boolean {
  const s = text.trim();
  return s.endsWith("?") || QUESTION_WORDS.test(s) || REQUEST_VERBS.test(s);
}

let seq = 0;
const nextId = () => `m${++seq}`;

export function Chat({
  session,
  onSignOut,
}: {
  session: Session;
  onSignOut: () => void;
}) {
  const greeting = (): Message => ({
    id: nextId(),
    role: "note",
    text: `Tell me things and I'll keep them${
      session.name ? `, ${session.name}` : ""
    }. Ask me things and I'll answer from what you've told me.`,
  });
  const [messages, setMessages] = useState<Message[]>([greeting()]);
  const [draft, setDraft] = useState("");
  const [attached, setAttached] = useState<PickedImage | null>(null);
  const [busy, setBusy] = useState(false);
  const [unsettled, setUnsettled] = useState(0);
  const [chatId, setChatId] = useState<string | null>(null);
  // A reply in flight, and how to stop it. Leaving the screen must actually
  // abort the request rather than let it call back into a gone component.
  const streamingRef = useRef(false);
  const cancelRef = useRef<null | (() => void)>(null);
  const [chatTitle, setChatTitle] = useState("New chat");
  const [listOpen, setListOpen] = useState(false);
  const [attachOpen, setAttachOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Set when the drawer's Settings row is tapped, read when the drawer reports
  // it has closed. A ref rather than state: nothing renders differently for it,
  // and it must survive the render the drawer's closure triggers.
  const wantsSettings = useRef(false);
  // Grows out of the + button rather than sliding up from the bottom of the
  // screen, so the menu reads as belonging to the control that opened it.
  const attachAnim = useRef(new Animated.Value(0)).current;
  const listRef = useRef<FlatList<Message>>(null);
  // Real device insets. The header sat under the notch and the composer under
  // the home indicator when these were guessed at with fixed padding.
  const insets = useSafeAreaInsets();

  // Android needs the keyboard handled in JS.
  //
  // KeyboardAvoidingView has no behavior on Android, because the platform is
  // supposed to resize the window itself — but Expo SDK 54+ turns on
  // edge-to-edge by default, and under edge-to-edge that resize no longer
  // moves the composer, so the keyboard covers the very field being typed in.
  // The usual fix, `softwareKeyboardLayoutMode` in app.json, is build-time
  // native config that Expo Go ignores, so it cannot help during development.
  //
  // Measuring the keyboard and padding the view is the one approach that works
  // in Expo Go and in a standalone build, on both platforms.
  const [keyboard, setKeyboard] = useState(0);
  useEffect(() => {
    const showEvent =
      Platform.OS === "ios" ? "keyboardWillShow" : "keyboardDidShow";
    const hideEvent =
      Platform.OS === "ios" ? "keyboardWillHide" : "keyboardDidHide";
    const shown = Keyboard.addListener(showEvent, (e) =>
      setKeyboard(e.endCoordinates?.height ?? 0),
    );
    const hidden = Keyboard.addListener(hideEvent, () => setKeyboard(0));
    return () => {
      shown.remove();
      hidden.remove();
    };
  }, []);

  // An answer still being written when the screen goes away is abandoned, not
  // awaited: without this the XHR keeps firing progress callbacks into a
  // component that no longer exists.
  useEffect(() => () => cancelRef.current?.(), []);

  // The web app's settling tray becomes one line in the header. This endpoint
  // reads in-process state and never reaches Reeve, so polling it is free.
  const refreshPending = useCallback(() => {
    api
      .pending()
      .then((items) =>
        setUnsettled(
          items.filter(
            (i) => i.status === "indexing" || i.status === "likely_indexed",
          ).length,
        ),
      )
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    refreshPending();
    const timer = setInterval(refreshPending, 5000);
    return () => clearInterval(timer);
  }, [refreshPending]);

  /** Open a conversation, replacing what is on screen with its transcript. */
  const openChat = useCallback(async (id: string) => {
    setChatId(id);
    try {
      const chat = await api.chat(id);
      setChatTitle(chat.title);
      setMessages(
        chat.messages.length
          ? chat.messages.map((m) => ({
              id: nextId(),
              role: m.role,
              text: m.text,
              meta: m.meta ?? undefined,
              question: m.question ?? undefined,
              // Server-hosted thumbnail, so a transcript still shows its photos
              // on a device that never held the original file.
              image: m.thumb_url
                ? { uri: `${API_BASE}${m.thumb_url}` }
                : undefined,
            }))
          : [greeting()],
      );
    } catch {
      setMessages([greeting()]);
    }
  }, []);

  // Resume the most recent conversation, or start the first one.
  useEffect(() => {
    (async () => {
      try {
        const all = await api.chats();
        if (all.length) await openChat(all[0].id);
        else {
          const fresh = await api.createChat();
          setChatId(fresh.id);
          setChatTitle(fresh.title);
        }
      } catch {
        /* offline — the chat still works, it just will not persist */
      }
    })();
  }, [openChat]);

  /** Persist rendered bubbles. Fire-and-forget: failing to save a transcript
   *  must never cost someone the answer they are reading. */
  const persist = (items: StoredMessage[]) => {
    if (!chatId) return;
    api
      .appendMessages(chatId, items)
      .then((c) => setChatTitle(c.title))
      .catch(() => undefined);
  };

  const push = (m: Omit<Message, "id">) => {
    setMessages((prev) => [...prev, { ...m, id: nextId() }]);
    setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 50);
  };

  /** Offer the two ways a photo can arrive.
   *
   *  A popover anchored to the + rather than a system action sheet. An alert
   *  interrupts and arrives from nowhere; a menu that grows out of the button
   *  keeps the connection between what was pressed and what opened.
   */
  const toggleAttachMenu = (open: boolean) => {
    if (open) setAttachOpen(true);
    Animated.timing(attachAnim, {
      toValue: open ? 1 : 0,
      duration: open ? 160 : 120,
      easing: Easing.out(Easing.quad),
      useNativeDriver: true,
    }).start(({ finished }) => {
      if (finished && !open) setAttachOpen(false);
    });
  };

  const attach = () => {
    if (busy) return;
    toggleAttachMenu(!attachOpen);
  };

  const chooseSource = (source: "camera" | "library") => {
    toggleAttachMenu(false);
    // Let the menu finish closing before the picker takes over the screen.
    setTimeout(() => pickFrom(source), 130);
  };

  const pickFrom = async (source: "camera" | "library") => {
    const perm =
      source === "camera"
        ? await ImagePicker.requestCameraPermissionsAsync()
        : await ImagePicker.requestMediaLibraryPermissionsAsync();

    if (!perm.granted) {
      push({
        role: "note",
        text:
          source === "camera"
            ? "Camera access is off, so I can't take a photo."
            : "Photo access is off, so I can't attach anything.",
      });
      return;
    }
    // quality is capped because the server rejects anything over 4 MB, and a
    // modern phone photo clears that comfortably — better to compress here than
    // to have the upload fail after the wait.
    const options = { mediaTypes: ["images"] as ["images"], quality: 0.7 };
    const result =
      source === "camera"
        ? await ImagePicker.launchCameraAsync(options)
        : await ImagePicker.launchImageLibraryAsync({
            ...options,
            allowsMultipleSelection: false,
          });

    if (result.canceled) return;

    const asset = result.assets?.[0];
    if (!asset?.uri) {
      // Selection came back with nothing usable. Saying so beats a screen that
      // silently looks like the tap never happened.
      push({
        role: "note",
        text: "Couldn't read that photo. Try another one.",
      });
      return;
    }
    setAttached({
      uri: asset.uri,
      mimeType: asset.mimeType,
      fileName: asset.fileName,
      width: asset.width,
      height: asset.height,
    });
  };

  const send = async () => {
    const text = draft.trim();
    if ((!text && !attached) || busy) return;

    const image = attached ?? undefined;
    push({ role: "you", text, image });
    setDraft("");
    setAttached(null);
    setBusy(true);

    try {
      if (image && isQuestion(text)) {
        const r = await api.askWithPhoto(image, text);
        const meta = `${(r.took_ms / 1000).toFixed(1)}s`;
        push({ role: "Carrel", text: r.answer, meta });
        persist([
          { role: "you", text },
          { role: "Carrel", text: r.answer, meta },
        ]);
      } else if (image) {
        const stored = await api.storePhoto(image, text || "A photo.");
        const note = "Photo kept. Searchable in half a minute or so.";
        push({ role: "note", text: note });
        persist([
          // The server-hosted thumbnail, not the device path, so the transcript
          // still shows the photo elsewhere.
          {
            role: "you",
            text,
            thumb_url: `/api/photos/${stored.photo_id}/raw`,
          },
          { role: "note", text: note },
        ]);
        refreshPending();
      } else {
        await converse(text);
      }
    } catch (e) {
      const err = e instanceof ApiError ? e : null;
      if (err?.status === 401) return onSignOut();
      push({ role: "note", text: err ? err.message : String(e) });
    } finally {
      if (!streamingRef.current) setBusy(false);
    }
  };

  /**
   * One turn of conversation, rendered as it arrives.
   *
   * An empty Carrel bubble goes up immediately and fills in. That bubble is
   * addressed by id rather than by "the last message", because a photo write
   * or a pending refresh can append while tokens are still coming and the last
   * message stops being the one being written.
   *
   * Nothing is persisted until the reply is complete: a transcript containing
   * half a sentence, saved because the network died mid-stream, is worse than
   * no transcript, and there is nothing to resume it with.
   */
  const converse = async (text: string) => {
    const id = nextId();
    setMessages((prev) => [
      ...prev,
      { id, role: "Carrel", text: "", streaming: true },
    ]);
    streamingRef.current = true;

    // Bedrock does not stream a token at a time. Measured against Mistral, a
    // 900-character reply arrives as five chunks of about 180 characters, so
    // appending each one as it lands makes the text jump in four or five
    // blocks — which reads as "not streaming" no matter how live the socket is.
    //
    // So the text is buffered and revealed at a readable pace. Nothing is
    // faked: every character shown has already arrived. The reveal only ever
    // trails the network, and it catches up rather than falling behind — the
    // more there is waiting, the faster it goes, so a long answer never ends up
    // typing itself out for a minute after the server has finished.
    let buffer = "";
    let shown = 0;
    let timer: ReturnType<typeof setInterval> | null = null;
    let finish: (() => void) | null = null;

    const stopReveal = () => {
      if (timer) clearInterval(timer);
      timer = null;
    };

    const startReveal = () => {
      if (timer) return;
      timer = setInterval(() => {
        const pending = buffer.length - shown;
        if (pending > 0) {
          // A floor of two characters keeps short replies moving; the divisor
          // drains a backlog quickly without ever outrunning what has arrived.
          const step = Math.max(2, Math.ceil(pending / 8));
          shown = Math.min(buffer.length, shown + step);
          const visible = buffer.slice(0, shown);
          setMessages((prev) =>
            prev.map((m) => (m.id === id ? { ...m, text: visible } : m)),
          );
          return;
        }
        // Caught up. The server may already have finished, in which case
        // completing here is what stops the reply being snapped to its full
        // text mid-reveal — which is what happens when a short answer arrives
        // in a single chunk and `done` lands a moment later.
        if (finish) {
          stopReveal();
          finish();
        }
      }, 28);
    };

    await new Promise<void>((resolve) => {
      const cancel = api.converse(text, chatId, {
        token: (piece) => {
          buffer += piece;
          startReveal();
        },
        done: (d) => {
          const complete = () => {
            // Storing used to announce itself with the word "Remembered." That
          // went away with the conversational reply, and nothing replaced it —
          // so a fact going into the graph and idle chatter looked identical,
          // and the honest reaction was "it isn't storing anything". The
          // acknowledgement is the model's job; saying so plainly is the app's.
          const meta = d.stored
            ? `${(d.took_ms / 1000).toFixed(1)}s · kept`
            : `${(d.took_ms / 1000).toFixed(1)}s`;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === id
                  ? {
                      ...m,
                      text: d.answer || m.text,
                      meta,
                      streaming: false,
                      // The sources link appears only where there are sources;
                      // `question` is what the evidence panel re-queries with.
                      question: d.evidence ? text : undefined,
                    }
                  : m,
              ),
            );
            persist([
              { role: "you", text },
              {
                role: "Carrel",
                text: d.answer,
                question: d.evidence ? text : undefined,
                meta,
              },
            ]);
            // A statement just went into the graph, so the settling count moved.
            if (d.stored) refreshPending();
            streamingRef.current = false;
            setBusy(false);
            resolve();
          };

          // Let the reveal drain first, unless it has nothing left to show.
          if (timer && shown < buffer.length) finish = complete;
          else {
            stopReveal();
            complete();
          }
        },
        error: (message) => {
          stopReveal();
          // Drop the empty bubble rather than leaving a blank one on screen.
          setMessages((prev) => prev.filter((m) => m.id !== id));
          push({ role: "note", text: message });
          streamingRef.current = false;
          setBusy(false);
          resolve();
        },
      });
      cancelRef.current = cancel;
    });
  };

  // Swipe in from the left edge to open the drawer — the other half of the
  // gesture. Without it the panel can be thrown shut but only tapped open,
  // which is the kind of asymmetry that makes an interface feel unfinished.
  // Confined to a narrow strip so it never competes with scrolling the
  // conversation or selecting text in a bubble.
  const touchStartX = useRef(0);
  const edgeSwipe = useRef(
    PanResponder.create({
      // Capture variants, because a PanResponder on a parent never sees a
      // gesture that a child FlatList has already claimed. Capture runs before
      // children, so a horizontal drag from the edge is intercepted while
      // ordinary vertical scrolling still reaches the list untouched.
      onStartShouldSetPanResponderCapture: (e) => {
        touchStartX.current = e.nativeEvent.pageX;
        return false; // observe only; do not steal the tap
      },
      onMoveShouldSetPanResponderCapture: (_, g) =>
        touchStartX.current < 32 &&
        g.dx > 10 &&
        Math.abs(g.dx) > Math.abs(g.dy) * 1.5,
      onPanResponderRelease: (_, g) => {
        if (g.dx > 40) setListOpen(true);
      },
    }),
  ).current;

  /** Re-run something that was stored as a memory, as a question instead. */
  const askAnyway = async (text: string) => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await api.ask(text);
      push({
        role: "Carrel",
        text: r.answer,
        question: text,
        meta: `${(r.took_ms / 1000).toFixed(1)}s`,
      });
    } catch (e) {
      push({
        role: "note",
        text: e instanceof ApiError ? e.message : String(e),
      });
    } finally {
      setBusy(false);
    }
  };

  const showEvidence = async (m: Message) => {
    if (!m.question || busy) return;
    setBusy(true);
    try {
      const { parsed } = await api.context(m.question);
      setMessages((prev) =>
        prev.map((x) => (x.id === m.id ? { ...x, evidence: parsed } : x)),
      );
    } catch (e) {
      push({
        role: "note",
        text: e instanceof ApiError ? e.message : String(e),
      });
    } finally {
      setBusy(false);
    }
  };

  const renderItem = ({ item }: { item: Message }) => {
    if (item.role === "note") {
      return (
        <View style={s.noteWrap}>
          <Text style={s.noteText}>{item.text}</Text>
          {item.askInstead && (
            <Pressable onPress={() => askAnyway(item.askInstead!)} hitSlop={8}>
              <Text style={s.noteLink}>ask it instead</Text>
            </Pressable>
          )}
        </View>
      );
    }
    const mine = item.role === "you";
    return (
      <View style={[s.row, mine ? s.rowMine : s.rowTheirs]}>
        <View style={[s.bubble, mine ? s.bubbleMine : s.bubbleTheirs]}>
          {item.image && <AuthImage uri={item.image.uri} style={s.image} />}
          {/* Carrel's own answers may carry the little Markdown a model emits;
              what the user typed is shown exactly as they typed it, stars and
              all, because there it is content rather than formatting. */}
          {mine ? (
            !!item.text && <Text style={s.bubbleText}>{item.text}</Text>
          ) : item.streaming ? (
            // Plain Text while the tokens land: a half-written "**" would
            // otherwise flicker between bold and literal as the pair completes.
            // The caret is what makes a pause read as thinking rather than as
            // a hang.
            <Text style={s.bubbleText}>
              {item.text}
              <Text style={s.caret}>▌</Text>
            </Text>
          ) : (
            !!item.text && <RichText style={s.bubbleText}>{item.text}</RichText>
          )}
          {!!item.meta && <Text style={s.meta}>{item.meta}</Text>}

          {item.question && !item.evidence && (
            <Pressable onPress={() => showEvidence(item)} hitSlop={8}>
              <Text style={s.link}>show what this came from</Text>
            </Pressable>
          )}
          {item.evidence && <Evidence ctx={item.evidence} />}
        </View>
      </View>
    );
  };

  return (
    <View style={s.screen} {...edgeSwipe.panHandlers}>
      <View style={[s.header, { paddingTop: insets.top + 8 }]}>
        {/* Drawn from three plain Views rather than pulled in as an icon font.
            An icon library is a dependency and a bundle cost for one glyph that
            is three rectangles. */}
        <Pressable
          onPress={() => setListOpen(true)}
          hitSlop={12}
          style={s.menuBtn}
          accessibilityRole="button"
          accessibilityLabel="Conversations"
        >
          <View style={s.menuLine} />
          <View style={s.menuLine} />
          <View style={s.menuLine} />
        </Pressable>

        <View style={s.headerCentre}>
          <Text style={s.brand} numberOfLines={1}>
            {chatTitle === "New chat" ? "Carrel" : chatTitle}
          </Text>
          {/* Only speaks when it has something to say. The signed-in address
              was here and earned its place on no screen: the person knows who
              they are, and a permanent subtitle trains the eye to ignore the
              one line that occasionally carries real news. */}
          {unsettled > 0 && (
            <Text style={s.status}>{unsettled} still settling</Text>
          )}
        </View>
        {/* No sign-out here. It lives in Settings, next to the other things
            that end a session, and a permanent exit in the corner of the screen
            you spend all your time on is a button whose only use is being hit
            by mistake. */}
      </View>

      <ChatList
        visible={listOpen}
        currentId={chatId}
        session={session}
        onPick={openChat}
        // Settings is opened here, on the drawer's own report that it has
        // finished closing, rather than inside the drawer on a timer. The
        // drawer is a real iOS modal; anything that appears while it is still
        // presented is at the mercy of UIKit's presentation stack.
        onClose={() => {
          setListOpen(false);
          if (wantsSettings.current) {
            wantsSettings.current = false;
            setSettingsOpen(true);
          }
        }}
        onSettings={() => {
          wantsSettings.current = true;
        }}
      />

      <Settings
        visible={settingsOpen}
        session={session}
        onClose={() => setSettingsOpen(false)}
        onSignedOut={() => {
          setSettingsOpen(false);
          onSignOut();
        }}
      />

      <KeyboardAvoidingView
        style={[
          s.flex,
          // iOS handles this natively; on Android the measured height is the
          // only thing that keeps the composer above the keyboard.
          Platform.OS === "android" && keyboard > 0
            ? { paddingBottom: keyboard }
            : null,
        ]}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        keyboardVerticalOffset={Platform.OS === "ios" ? 8 : 0}
      >
        <FlatList
          ref={listRef}
          data={messages}
          keyExtractor={(m) => m.id}
          renderItem={renderItem}
          contentContainerStyle={s.list}
          onContentSizeChange={() =>
            listRef.current?.scrollToEnd({ animated: false })
          }
          keyboardDismissMode="interactive"
        />

        {attached && (
          <View style={s.attachBar}>
            <Image source={{ uri: attached.uri }} style={s.attachThumb} />
            <Text style={s.attachHint}>
              Add a caption to keep it, or ask about it.
            </Text>
            <Pressable onPress={() => setAttached(null)} hitSlop={10}>
              <Text style={s.link}>remove</Text>
            </Pressable>
          </View>
        )}

        {attachOpen && (
          /* Anywhere else dismisses, the way a menu should. */
          <Pressable
            style={s.attachScrim}
            onPress={() => toggleAttachMenu(false)}
          />
        )}

        <View
          style={[
            s.composer,
            { paddingBottom: keyboard > 0 ? 10 : Math.max(insets.bottom, 10) },
          ]}
        >
          {/* Anchored to the composer, not to the screen.
              It used to be an absolute child of the keyboard-padded container
              with `bottom: <inset> + 56`, and Yoga measures an absolute child's
              offset from the container's full box rather than from the padding
              it was given. With the keyboard up that put the menu ~66px from the
              bottom of the WINDOW — underneath the keyboard. The + rotated into
              an x, so the menu had opened; it was simply drawn where nobody
              could see it. Hanging it off the composer means it inherits
              whatever keeps the composer above the keyboard, on both platforms,
              with no second copy of that arithmetic to keep in step. */}
          {attachOpen && (
            <Animated.View
              style={[
                s.attachMenu,
                {
                  opacity: attachAnim,
                  transform: [
                    {
                      translateY: attachAnim.interpolate({
                        inputRange: [0, 1],
                        outputRange: [10, 0],
                      }),
                    },
                    {
                      scale: attachAnim.interpolate({
                        inputRange: [0, 1],
                        outputRange: [0.92, 1],
                      }),
                    },
                  ],
                },
              ]}
            >
              <Pressable
                style={s.attachItem}
                onPress={() => chooseSource("camera")}
              >
                <Text style={s.attachGlyphSm}>◎</Text>
                <Text style={s.attachLabel}>Take a photo</Text>
              </Pressable>
              <View style={s.attachDivider} />
              <Pressable
                style={s.attachItem}
                onPress={() => chooseSource("library")}
              >
                <Text style={s.attachGlyphSm}>▤</Text>
                <Text style={s.attachLabel}>Choose from library</Text>
              </Pressable>
            </Animated.View>
          )}

          <Pressable
            style={s.attachBtn}
            onPress={attach}
            disabled={busy}
            hitSlop={6}
          >
            <Animated.Text
              style={[
                s.attachGlyph,
                {
                  transform: [
                    {
                      rotate: attachAnim.interpolate({
                        inputRange: [0, 1],
                        outputRange: ["0deg", "45deg"],
                      }),
                    },
                  ],
                },
              ]}
            >
              +
            </Animated.Text>
          </Pressable>
          <TextInput
            style={s.input}
            value={draft}
            onChangeText={setDraft}
            placeholder="Tell me something, or ask…"
            placeholderTextColor={t.color.inkTertiary}
            multiline
            editable={!busy}
          />
          <Pressable
            style={[
              s.send,
              (busy || (!draft.trim() && !attached)) && s.sendOff,
            ]}
            onPress={send}
            disabled={busy || (!draft.trim() && !attached)}
          >
            {busy ? (
              <ActivityIndicator size="small" color={t.color.accentInk} />
            ) : (
              <Text style={s.sendGlyph}>↑</Text>
            )}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </View>
  );
}

/** Trimmed to what is worth reading on a phone: the facts, with replaced ones
 *  struck through. The full raw context stays on the web version — nobody reads
 *  two kilobytes of it on a handset. */
function Evidence({ ctx }: { ctx: ParsedContext }) {
  const states = ctx.episodes.flatMap((e) => e.states);
  const replaced = states.filter((x) => x.superseded).length;

  if (ctx.empty && ctx.pending.length === 0) {
    return <Text style={s.evidenceEmpty}>Nothing matched.</Text>;
  }
  return (
    <View style={s.evidence}>
      <Text style={s.evidenceHead}>
        {ctx.episodes.length} memories
        {replaced > 0 ? ` · ${replaced} replaced` : ""}
      </Text>
      {states.map((st, i) => (
        <Text key={i} style={[s.fact, st.superseded && s.factOld]}>
          {st.attribute}: {st.value}
        </Text>
      ))}
      {ctx.episodes.slice(0, 3).map((ep, i) => (
        <Text key={`e${i}`} style={s.episode} numberOfLines={2}>
          · {ep.display}
        </Text>
      ))}
    </View>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: t.color.bg },
  flex: { flex: 1 },

  menuBtn: {
    // 44x44 is the smallest reliable touch target on both platforms. The glyph
    // is 18px wide, and sizing the button to the glyph meant only a precise tap
    // on the lines themselves registered — hitSlop alone was not enough,
    // because it expands the press area but the layout still reserved 30px.
    width: 44,
    height: 44,
    justifyContent: "center",
    alignItems: "flex-start",
    gap: 4,
    marginRight: 4,
    marginLeft: -6, // keeps the glyph optically aligned to the screen edge
  },
  menuLine: {
    height: 1.5,
    width: 18,
    borderRadius: 1,
    backgroundColor: t.color.ink,
  },
  headerCentre: { flex: 1 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 20,
    paddingBottom: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: t.color.border,
  },
  brand: { color: t.color.ink, ...t.text.title, fontSize: 20 },
  status: { color: t.color.inkTertiary, ...t.text.small, marginTop: 1 },

  list: { padding: 16, paddingBottom: 10 },

  noteWrap: { alignItems: "center", marginVertical: 10, paddingHorizontal: 24 },
  noteText: {
    color: t.color.inkTertiary,
    ...t.text.small,
    textAlign: "center",
    lineHeight: 18,
  },
  noteLink: {
    color: t.color.accent,
    ...t.text.small,
    textAlign: "center",
    marginTop: 4,
  },

  row: { marginVertical: 5, flexDirection: "row" },
  rowMine: { justifyContent: "flex-end" },
  rowTheirs: { justifyContent: "flex-start" },
  bubble: {
    maxWidth: "86%",
    borderRadius: t.radius.md,
    paddingHorizontal: 14,
    paddingVertical: 11,
  },
  bubbleMine: { backgroundColor: t.color.accentSoft, borderTopRightRadius: 4 },
  bubbleTheirs: {
    backgroundColor: t.color.card,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: t.color.border,
    borderTopLeftRadius: 4,
  },
  bubbleText: { color: t.color.ink, ...t.text.body },
  caret: { color: t.color.accent },
  image: {
    width: 210,
    height: 145,
    borderRadius: t.radius.sm,
    marginBottom: 8,
  },
  meta: { color: t.color.inkTertiary, ...t.text.mono, marginTop: 7 },
  link: { color: t.color.accent, ...t.text.small, marginTop: 8 },

  evidence: {
    marginTop: 10,
    paddingTop: 9,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: t.color.border,
  },
  evidenceHead: {
    color: t.color.inkTertiary,
    ...t.text.mono,
    textTransform: "uppercase",
    letterSpacing: 0.6,
    marginBottom: 6,
  },
  evidenceEmpty: { color: t.color.inkSecondary, ...t.text.small, marginTop: 8 },
  fact: { color: t.color.inkSecondary, ...t.text.mono, marginBottom: 3 },
  factOld: { textDecorationLine: "line-through", color: t.color.inkTertiary },
  episode: { color: t.color.inkTertiary, ...t.text.mono, marginTop: 4 },

  attachBar: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 16,
    paddingVertical: 9,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: t.color.border,
  },
  attachThumb: { width: 42, height: 42, borderRadius: t.radius.sm },
  attachHint: { color: t.color.inkSecondary, ...t.text.small, flex: 1 },

  composer: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: 8,
    paddingHorizontal: 12,
    paddingTop: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: t.color.border,
  },
  attachScrim: {
    position: "absolute",
    left: 0,
    right: 0,
    top: 0,
    bottom: 0,
  },
  attachMenu: {
    position: "absolute",
    left: 12,
    // Sits directly on top of the composer row, wherever that row happens to be.
    bottom: "100%",
    marginBottom: 8,
    backgroundColor: t.color.cardRaised,
    borderRadius: t.radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: t.color.borderStrong,
    paddingVertical: 4,
    minWidth: 210,
    // Grows from its bottom-left corner, where the + sits.
    transformOrigin: "0% 100%",
  },
  attachItem: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 12,
    paddingHorizontal: 14,
  },
  attachGlyphSm: {
    color: t.color.accent,
    fontSize: 15,
    width: 18,
    textAlign: "center",
  },
  attachLabel: { color: t.color.ink, ...t.text.body, fontSize: 15 },
  attachDivider: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: t.color.border,
    marginHorizontal: 12,
  },
  attachBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: t.color.card,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: t.color.borderStrong,
  },
  attachGlyph: { color: t.color.ink, fontSize: 22, marginTop: -3 },
  input: {
    flex: 1,
    color: t.color.ink,
    fontSize: 16,
    maxHeight: 130,
    minHeight: 40,
    paddingHorizontal: 15,
    paddingTop: 10,
    paddingBottom: 10,
    backgroundColor: t.color.card,
    borderRadius: 20,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: t.color.borderStrong,
  },
  send: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: t.color.accent,
  },
  sendOff: { opacity: 0.35 },
  sendGlyph: {
    color: t.color.accentInk,
    fontSize: 19,
    fontWeight: "700",
    marginTop: -2,
  },
});
