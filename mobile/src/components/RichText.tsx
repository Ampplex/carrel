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
 * parser, a plugin system and a stylesheet to solve four inline forms and three
 * block forms. This handles what the model emits and nothing else:
 *
 *   **bold**  __bold__  *italic*  `code`
 *   # heading   - bullet   1. numbered
 *
 * Deliberately NOT supported: links, images, tables, block quotes, nested
 * lists. None appear in an answer about where you left your keys, and each one
 * would need a rendering decision — what a link does when tapped, what a table
 * does at 380px — that nothing here is asking for.
 *
 * Only Carrel's own text goes through this. What someone typed themselves is
 * rendered literally: if you store "the file is called **draft**", the stars
 * are part of the note, and quietly eating them would be a data-loss bug
 * wearing a typography costume.
 */

import { Platform, StyleSheet, Text, TextStyle, View } from "react-native";
import { theme as t } from "../theme";

type Span = { text: string; bold?: boolean; italic?: boolean; code?: boolean };

type Block =
  | { kind: "p"; spans: Span[] }
  | { kind: "h"; spans: Span[] }
  | { kind: "li"; marker: string; spans: Span[] };

// One pass, alternation ordered longest-first so ** is never read as two *.
// Underscores are handled only in their doubled form: single ones appear inside
// file_name and snake_case far more often than they mean emphasis.
const INLINE = /(\*\*|__)([\s\S]+?)\1|\*([^\s*][\s\S]*?)\*|`([^`]+)`/g;

function parseInline(src: string): Span[] {
  const spans: Span[] = [];
  let last = 0;
  for (const m of src.matchAll(INLINE)) {
    const at = m.index ?? 0;
    if (at > last) spans.push({ text: src.slice(last, at) });
    if (m[2] !== undefined) spans.push({ text: m[2], bold: true });
    else if (m[3] !== undefined) spans.push({ text: m[3], italic: true });
    else if (m[4] !== undefined) spans.push({ text: m[4], code: true });
    last = at + m[0].length;
  }
  if (last < src.length) spans.push({ text: src.slice(last) });
  return spans.length ? spans : [{ text: src }];
}

const HEADING = /^\s{0,3}(#{1,6})\s+(.*)$/;
const BULLET = /^\s*[-*+]\s+(.*)$/;
const ORDERED = /^\s*(\d+)[.)]\s+(.*)$/;

function parseBlocks(src: string): Block[] {
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
      blocks.push({ kind: "li", marker: `${ordered[1]}.`, spans: parseInline(ordered[2]) });
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
      {spans.map((s, i) => (
        <Text key={i} style={spanStyle(s)}>
          {s.text}
        </Text>
      ))}
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
  code: {
    // RN has no cross-platform monospace alias; these are the system faces.
    fontFamily: Platform.select({ ios: "Menlo", default: "monospace" }),
    backgroundColor: t.color.card,
  },
});
