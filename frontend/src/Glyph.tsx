/**
 * Tiny inline SVG glyphs — replace text symbols (✓ ⚠ ✕ 📄) that render as
 * escaped artefacts (\2713 …) in RTL copy or when text is copied.
 * `flip` mirrors glyph geometry for RTL layouts where the mark reads backwards.
 */
export type GlyphName =
  | "check"
  | "cross"
  | "warning"
  | "doc"
  | "eye"
  | "eye-off"
  | "clock";

export function Glyph({
  name,
  size = 11,
  className,
}: {
  name: GlyphName;
  size?: number;
  className?: string;
}) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none" as const,
    "aria-hidden": true,
    className: `glyph glyph-${name}${className ? " " + className : ""}`,
  };
  switch (name) {
    case "check":
      return (
        <svg {...common}>
          <path
            d="M4.5 12.5l5 5L19.5 7"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "cross":
      return (
        <svg {...common}>
          <path
            d="M6 6l12 12M18 6L6 18"
            stroke="currentColor"
            strokeWidth="2.6"
            strokeLinecap="round"
          />
        </svg>
      );
    case "warning":
      return (
        <svg {...common}>
          <path
            d="M12 3.5L22 20H2L12 3.5z"
            fill="currentColor"
          />
          <path
            d="M12 9.5v5"
            stroke="#fff"
            strokeWidth="2.4"
            strokeLinecap="round"
          />
          <circle cx="12" cy="17.4" r="1.35" fill="#fff" />
        </svg>
      );
    case "doc":
      return (
        <svg {...common}>
          <path
            d="M6 3.5h8.5L19 8v12.5H6z"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinejoin="round"
          />
          <path d="M14 3.5V8h5" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
          <path d="M9 16.5v-3M12 16.5v-5M15 16.5v-1.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      );
    case "eye":
      return (
        <svg {...common}>
          <path
            d="M2.5 12S6 5.8 12 5.8 21.5 12 21.5 12 18 18.2 12 18.2 2.5 12 2.5 12z"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinejoin="round"
          />
          <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="2" />
        </svg>
      );
    case "clock":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" />
          <path
            d="M12 7v5l3.5 2"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "eye-off":
      return (
        <svg {...common}>
          <path
            d="M4 4l16 16"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
          />
          <path
            d="M9.9 5.2A9.6 9.6 0 0112 5c6 0 9.5 7 9.5 7a17 17 0 01-2.8 3.7M6.2 6.9A16.6 16.6 0 002.5 12S6 19 12 19c1.5 0 2.9-.4 4.1-1M9.9 9.9a3 3 0 004.2 4.2"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
  }
}

export default Glyph;
