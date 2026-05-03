import type { Config } from "tailwindcss";

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
        bg: { DEFAULT: "#0b0d10", soft: "#12161a", subtle: "#181d22" },
        line: "#262d34",
        ink: { DEFAULT: "#e7eaee", muted: "#9aa3ad", soft: "#6b7480" },
        bull: "#22c55e",
        bear: "#ef4444",
        warn: "#f59e0b",
        accent: "#7c9cff",
      },
      fontFamily: {
        sans: ['ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
};

export default config;
