/**
 * Dark only.
 *
 * Not a light theme with the values flipped — the palette is built for a dark
 * surface from the start, which mostly means two things. Pure black is avoided
 * (#0D0C0A reads as a material rather than a hole), and text never runs at full
 * white, because #FFF on near-black vibrates. The warm cast is deliberate: this
 * is a place for notes, and a cold blue-grey UI makes prose feel like telemetry.
 *
 * Colour carries meaning and nothing else:
 *   accent      interactive, and only interactive
 *   amber       in flight, or a fact that has been replaced
 *   danger      failed
 */

export const theme = {
  color: {
    bg: "#0D0C0A",
    surface: "#17161300",
    card: "#1A1815",
    cardRaised: "#221F1B",
    border: "#2C2823",
    borderStrong: "#3D3831",

    ink: "#EDE8DE",
    inkSecondary: "#A69E90",
    inkTertiary: "#6F6759",

    accent: "#8FB9A8",
    accentPressed: "#7AA492",
    accentInk: "#0D1512",
    accentSoft: "#18251F",

    amber: "#D7A34C",
    amberSoft: "#241D11",
    danger: "#D98872",
    dangerSoft: "#241512",
    success: "#7CB894",
    successSoft: "#16231A",
  },

  /** 4px rhythm. */
  space: (n: number) => n * 4,

  radius: { sm: 8, md: 14, lg: 20, pill: 999 },

  text: {
    display: { fontSize: 32, lineHeight: 38, fontWeight: "700" as const, letterSpacing: -0.6 },
    title: { fontSize: 22, lineHeight: 28, fontWeight: "600" as const, letterSpacing: -0.3 },
    body: { fontSize: 15.5, lineHeight: 22 },
    label: { fontSize: 13, lineHeight: 18, fontWeight: "600" as const },
    small: { fontSize: 12, lineHeight: 16 },
    mono: { fontSize: 11.5, lineHeight: 17 },
  },
};

export type Theme = typeof theme;
