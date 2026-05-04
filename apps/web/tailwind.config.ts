import type { Config } from "tailwindcss";

/**
 * Design tokens for TradingAI.
 *
 * Reference points: Bloomberg Terminal density, Stripe clarity, TradingView
 * chart readability. Dark mode primary, light mode supported via the
 * data-theme="light" attribute set by ThemeApplier.
 *
 * Tokens are organized as:
 *   - Surfaces (bg / bg.soft / bg.subtle / bg.elevated)
 *   - Ink (default / muted / soft / inverse)
 *   - Semantic colors (bull / bear / warn / info / accent) — each with a
 *     50/100/200/.../900 scale so we can build subtle backgrounds, borders,
 *     and emphatic accents without inventing colors at the call site.
 *   - Lines (default / strong / accent)
 *   - Type scale (display / h1-h4 / body / caption / mono-tabular)
 *   - Radii, shadows, motion, z-indexes.
 *
 * Existing tokens (bg, ink, bull, bear, warn, accent without scale) stay
 * intact for backwards compatibility; the new scales add `bull-50..900`,
 * `bear-50..900`, `accent-50..900` etc. that components/ui consumes.
 */
const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // ─── Surfaces ─────────────────────────────────────────────────────
        bg: {
          DEFAULT: "#0b0d10",      // page background
          soft: "#12161a",         // card surface
          subtle: "#181d22",       // recessed surface (input, code)
          elevated: "#1d2328",     // popover, tooltip, dropdown
        },

        // ─── Ink (text colors) ────────────────────────────────────────────
        ink: {
          DEFAULT: "#e7eaee",      // primary text
          muted: "#9aa3ad",        // secondary
          soft: "#6b7480",         // tertiary, captions
          inverse: "#0b0d10",      // text on light backgrounds
        },

        // ─── Lines / borders ──────────────────────────────────────────────
        line: {
          DEFAULT: "#262d34",
          strong: "#3a434c",
          accent: "#7c9cff",
        },

        // ─── Semantic — bull (gain / buy / success) ───────────────────────
        bull: {
          DEFAULT: "#22c55e",
          50: "#f0fdf4",
          100: "#dcfce7",
          200: "#bbf7d0",
          300: "#86efac",
          400: "#4ade80",
          500: "#22c55e",
          600: "#16a34a",
          700: "#15803d",
          800: "#166534",
          900: "#14532d",
        },

        // ─── Semantic — bear (loss / sell / error) ────────────────────────
        bear: {
          DEFAULT: "#ef4444",
          50: "#fef2f2",
          100: "#fee2e2",
          200: "#fecaca",
          300: "#fca5a5",
          400: "#f87171",
          500: "#ef4444",
          600: "#dc2626",
          700: "#b91c1c",
          800: "#991b1b",
          900: "#7f1d1d",
        },

        // ─── Semantic — warn (caution / pending / partial) ────────────────
        warn: {
          DEFAULT: "#f59e0b",
          50: "#fffbeb",
          100: "#fef3c7",
          200: "#fde68a",
          300: "#fcd34d",
          400: "#fbbf24",
          500: "#f59e0b",
          600: "#d97706",
          700: "#b45309",
          800: "#92400e",
          900: "#78350f",
        },

        // ─── Semantic — info / neutral-blue (used sparingly for hints) ────
        info: {
          DEFAULT: "#0ea5e9",
          50: "#f0f9ff",
          100: "#e0f2fe",
          200: "#bae6fd",
          300: "#7dd3fc",
          400: "#38bdf8",
          500: "#0ea5e9",
          600: "#0284c7",
          700: "#0369a1",
          800: "#075985",
          900: "#0c4a6e",
        },

        // ─── Brand accent (links, focus rings, primary buttons) ───────────
        accent: {
          DEFAULT: "#7c9cff",
          50: "#eef2ff",
          100: "#e0e7ff",
          200: "#c7d2fe",
          300: "#a5b4fc",
          400: "#818cf8",
          500: "#7c9cff",
          600: "#5d7df0",
          700: "#4456c2",
          800: "#374296",
          900: "#2c3678",
        },
      },

      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },

      // ─── Type scale ────────────────────────────────────────────────────
      // Used as `text-display` / `text-h1` etc. in JSX. Pairs size + leading
      // + tracking so callers don't have to remember the combo.
      fontSize: {
        // numeric tier (Tailwind defaults stay too)
        display: ["2.25rem", { lineHeight: "2.5rem", letterSpacing: "-0.02em", fontWeight: "600" }],
        h1: ["1.75rem", { lineHeight: "2.125rem", letterSpacing: "-0.02em", fontWeight: "600" }],
        h2: ["1.375rem", { lineHeight: "1.75rem", letterSpacing: "-0.015em", fontWeight: "600" }],
        h3: ["1.125rem", { lineHeight: "1.5rem", letterSpacing: "-0.01em", fontWeight: "600" }],
        h4: ["1rem", { lineHeight: "1.375rem", letterSpacing: "0", fontWeight: "600" }],
        body: ["0.9375rem", { lineHeight: "1.5rem" }],
        caption: ["0.8125rem", { lineHeight: "1.125rem" }],
        micro: ["0.6875rem", { lineHeight: "0.875rem", letterSpacing: "0.04em" }],
      },

      // ─── Radii ─────────────────────────────────────────────────────────
      borderRadius: {
        xs: "3px",
        sm: "4px",
        md: "6px",
        lg: "10px",
        xl: "14px",
        "2xl": "18px",
      },

      // ─── Shadows (dark-aware: lower opacity, slight blue tint) ─────────
      boxShadow: {
        subtle: "0 1px 0 0 rgba(0,0,0,0.4)",
        soft: "0 4px 12px -4px rgba(0,0,0,0.5)",
        elevated: "0 10px 30px -10px rgba(0,0,0,0.6), 0 2px 6px -2px rgba(0,0,0,0.4)",
        dialog: "0 24px 60px -20px rgba(0,0,0,0.7), 0 4px 12px -4px rgba(0,0,0,0.5)",
        focus: "0 0 0 2px rgba(124,156,255,0.4)",
        "focus-strong": "0 0 0 3px rgba(124,156,255,0.6)",
      },

      // ─── Motion ────────────────────────────────────────────────────────
      transitionDuration: {
        fast: "120ms",
        DEFAULT: "180ms",
        slow: "260ms",
      },
      transitionTimingFunction: {
        // standard for general motion; emphasized for entrances
        standard: "cubic-bezier(0.2, 0, 0, 1)",
        emphasized: "cubic-bezier(0.3, 0, 0, 1.2)",
      },

      // ─── z-index scale (avoid magic numbers in components) ─────────────
      zIndex: {
        nav: "30",
        dropdown: "40",
        modal: "50",
        toast: "60",
        tooltip: "70",
      },

      // ─── Animations the new primitives use ─────────────────────────────
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "slide-up": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-in": "fade-in 180ms cubic-bezier(0.2, 0, 0, 1)",
        "slide-up": "slide-up 220ms cubic-bezier(0.2, 0, 0, 1)",
      },
    },
  },
  plugins: [],
};

export default config;
