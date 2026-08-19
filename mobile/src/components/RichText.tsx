/**
 * The small amount of Markdown a language model actually emits, rendered.
 *
 * Answers arrive as prose most of the time, but not always: ask something
 * open-ended and the model reaches for `**bold**` headings and a numbered list.
 * Those were being drawn verbatim, so an answer came back reading
 * "3. **Relevant Textbooks**: if you have any materials..." — asterisks and all.
 * That is the sort of detail that makes an app feel unfinished, and it is
 * visible in the first screenshot anyone sees.
 *
 * A Markdown library would be the obvious reach, but every one of them brings a
 * parser, a plugin system and a stylesheet to solve a handful of forms. This
 * handles what the model emits and nothing else:
 *
 *   **bold**  __bold__  *italic*  `code`  [text](https://…)
 *   # heading   - bullet   1. numbered   ```fenced code```
 *
 * Deliberately NOT supported: images, tables, block quotes, nested lists. None
 * appear in an answer about where you left your keys, and each would need a
 * rendering decision — what a table does at 380px — that nothing here asks for.
 * Links were on that list too, until testing the parser directly against
 * realistic replies showed the actual failure: `[this guide](url)` rendered as
 * literal brackets and a bare URL, which reads as broken markdown rather than
 * an unsupported form. A link only has one sane action, so it is tappable.
 *
 * Only Carrel's own text goes through this. What someone typed themselves is
 * rendered literally: if you store "the file is called **draft**", the stars
 * are part of the note, and quietly eating them would be a data-loss bug
 * wearing a typography costume.
 */

import { Linking, Platform, StyleSheet, Text, TextStyle, View } from "react-native";
import { theme as t } from "../theme";

type Span = { text: string; bold?: boolean; italic?: boolean; code?: boolean; href?: string };

type Block =
  | { kind: "p"; spans: Span[] }
  | { kind: "h"; spans: Span[] }
  | { kind: "li"; marker: string; ordered?: boolean; spans: Span[] }
  | { kind: "code"; text: string };

// One pass, alternation ordered longest-first so ** is never read as two *.
// Underscores are handled only in their doubled form: single ones appear inside
// file_name and snake_case far more often than they mean emphasis. The link
// form is restricted to http(s) — a `javascript:` or `data:` URL has no
// business being tappable out of a memory answer.
const INLINE =
  /(\*\*|__)([\s\S]+?)\1|\*([^\s*][\s\S]*?)\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;

function parseInline(src: string): Span[] {
  const spans: Span[] = [];
  let last = 0;
  for (const m of src.matchAll(INLINE)) {
    const at = m.index ?? 0;
    if (at > last) spans.push({ text: src.slice(last, at) });
    if (m[2] !== undefined) spans.push({ text: m[2], bold: true });
    else if (m[3] !== undefined) spans.push({ text: m[3], italic: true });
    else if (m[4] !== undefined) spans.push({ text: m[4], code: true });
    else if (m[5] !== undefined) spans.push({ text: m[5], href: m[6] });
    last = at + m[0].length;
  }
  if (last < src.length) spans.push({ text: src.slice(last) });
  return spans.length ? spans : [{ text: src }];
}

const HEADING = /^\s{0,3}(#{1,6})\s+(.*)$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
// Two guards, both learned the hard way. The number is capped because "4417."
// is a locker code, not the four-thousand-four-hundred-and-seventeenth item —
// and an answer that opens with one was being drawn with the code in the
// marker column and the sentence indented beside it. And a lone numbered line
// is not a list: real lists come in runs, so a single one is left as prose.
const ORDERED = /^\s*(\d{1,2})[.)]\s+(.*)$/;
// A fence needs no closing partner to be found by the tokenizer that walks the
// whole string, so an unterminated ``` (the model cut off mid-block) simply
// fails to match here and falls through to line-by-line parsing below, which
// draws it as literal text — worse-looking than a rendered block, but never a
// crash and never silently dropped content.
const FENCE = /```[^\n]*\n?([\s\S]*?)```/g;

function parseTextBlocks(src: string): Block[] {
  const blocks: Block[] = [];
  for (const raw of src.split("\n")) {
    const line = raw.trimEnd();
    // A blank line between paragraphs is spacing, which the layout already
    // provides via `gap`. Rendering it as an empty Text would double it.
    if (!line.trim()) continue;

    const heading = line.match(HEADING);
    if (heading) {
      blocks.push({ kind: "h", spans: parseInline(heading[2]) });
      continue;
    }
    const ordered = line.match(ORDERED);
    if (ordered) {
      blocks.push({
        kind: "li",
        marker: `${ordered[1]}.`,
        ordered: true,
        spans: parseInline(ordered[2]),
      });
      continue;
    }
    const bullet = line.match(BULLET);
    if (bullet) {
      blocks.push({ kind: "li", marker: "•", spans: parseInline(bullet[1]) });
      continue;
    }
    blocks.push({ kind: "p", spans: parseInline(line) });
  }
  return blocks;
}

function parseBlocks(src: string): Block[] {
  const blocks: Block[] = [];
  let cursor = 0;
  FENCE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = FENCE.exec(src))) {
    blocks.push(...parseTextBlocks(src.slice(cursor, m.index)));
    // A code block is never re-parsed for **bold** or `code` inside it — a
    // snippet containing an asterisk for multiplication should not turn part
    // of itself italic.
    blocks.push({ kind: "code", text: m[1].replace(/\n$/, "") });
    cursor = m.index + m[0].length;
  }
  blocks.push(...parseTextBlocks(src.slice(cursor)));
  return demoteLoneNumbers(blocks);
}

/** A numbered item with no numbered neighbour was never a list. */
function demoteLoneNumbers(blocks: Block[]): Block[] {
  return blocks.map((b, i) => {
    if (b.kind !== "li" || !b.ordered) return b;
    const neighbour = (o: number) => {
      const n = blocks[i + o];
      return n && n.kind === "li" && n.ordered;
    };
    if (neighbour(-1) || neighbour(1)) return b;
    return { kind: "p", spans: [{ text: `${b.marker} ` }, ...b.spans] } as Block;
  });
}

function spanStyle(s: Span): TextStyle | undefined {
  if (s.code) return st.code;
  if (s.bold && s.italic) return st.boldItalic;
  if (s.bold) return st.bold;
  if (s.italic) return st.italic;
  return undefined;
}

function Spans({ spans }: { spans: Span[] }) {
  return (
    <>
      {spans.map((s, i) =>
        s.href ? (
          <Text
            key={i}
            style={st.link}
            onPress={() => {
              Linking.openURL(s.href!).catch(() => undefined);
            }}
          >
            {s.text}
          </Text>
        ) : (
          <Text key={i} style={spanStyle(s)}>
            {s.text}
          </Text>
        )
      )}
    </>
  );
}

export function RichText({ children, style }: { children: string; style?: TextStyle }) {
  const blocks = parseBlocks(children ?? "");

  // Nothing structural in it — the common case by far — so render one Text and
  // keep selection, line breaking and copy behaving exactly as before.
  if (blocks.length === 1 && blocks[0].kind === "p") {
    return (
      <Text style={style}>
        <Spans spans={blocks[0].spans} />
      </Text>
    );
  }

  return (
    <View style={st.blocks}>
      {blocks.map((b, i) => {
        if (b.kind === "code") {
          return (
            <View key={i} style={st.codeBlock}>
              <Text style={st.codeBlockText}>{b.text}</Text>
            </View>
          );
        }
        if (b.kind === "li") {
          return (
            <View key={i} style={st.row}>
              <Text style={[style, st.marker]}>{b.marker}</Text>
              <Text style={[style, st.flex]}>
                <Spans spans={b.spans} />
              </Text>
            </View>
          );
        }
        return (
          <Text key={i} style={[style, b.kind === "h" ? st.heading : null]}>
            <Spans spans={b.spans} />
          </Text>
        );
      })}
    </View>
  );
}

const st = StyleSheet.create({
  blocks: { gap: 6 },
  row: { flexDirection: "row", gap: 8 },
  // Fixed width so wrapped lines align under each other rather than under the
  // marker, which is what makes a list read as a list.
  marker: { minWidth: 18, opacity: 0.75 },
  flex: { flex: 1 },
  bold: { fontWeight: "700" },
  italic: { fontStyle: "italic" },
  boldItalic: { fontWeight: "700", fontStyle: "italic" },
  heading: { fontWeight: "700" },
  link: { color: t.color.accent, textDecorationLine: "underline" },
  code: {
    // RN has no cross-platform monospace alias; these are the system faces.
    fontFamily: Platform.select({ ios: "Menlo", default: "monospace" }),
    backgroundColor: t.color.card,
  },
  codeBlock: {
    backgroundColor: t.color.card,
    borderRadius: t.radius.sm,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: t.color.border,
    padding: 10,
  },
  codeBlockText: {
    fontFamily: Platform.select({ ios: "Menlo", default: "monospace" }),
    color: t.color.ink,
    fontSize: 13,
    lineHeight: 18,
  },
});
