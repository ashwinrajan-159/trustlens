/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Brand ramp — warm manila/bronze drawn from the dossier palette image
        // (#d0c0a0 manila, #e0d0b0 cream, ink-gray backdrop).
        brand: {
          50: "#faf7ef", 100: "#f2ecdb", 200: "#e6d9b8", 300: "#d6c193",
          400: "#c5a76a", 500: "#b18a45", 600: "#9a7434", 700: "#7c5c2c",
          800: "#654b28", 900: "#533e23", 950: "#2e2112",
        },
        // Ink — the stamp-black used for primary actions (dark pill buttons).
        ink: { DEFAULT: "#1c1917", soft: "#292524", mute: "#44403c" },
        // Paper/manila surfaces for the warm backdrop.
        paper: { DEFAULT: "#f5f1e8", deep: "#ece5d4", manila: "#d0c0a0" },
        // Semantic risk-tier palette — unchanged (severity must stay recognizable).
        risk: {
          low: "#059669",       // emerald
          medium: "#d97706",    // amber
          high: "#ea580c",      // orange
          critical: "#dc2626",  // red
        },
      },
      boxShadow: {
        card: "0 1px 2px 0 rgb(41 37 36 / 0.05), 0 2px 8px -2px rgb(41 37 36 / 0.08)",
        "card-hover": "0 6px 18px -4px rgb(41 37 36 / 0.14), 0 3px 8px -3px rgb(41 37 36 / 0.08)",
        glass: "0 1px 0 0 rgb(255 255 255 / 0.6) inset, 0 4px 16px -4px rgb(41 37 36 / 0.12)",
        focus: "0 0 0 3px rgb(177 138 69 / 0.25)",
      },
      keyframes: {
        "fade-in": { "0%": { opacity: "0", transform: "translateY(4px)" }, "100%": { opacity: "1", transform: "translateY(0)" } },
      },
      animation: { "fade-in": "fade-in 0.25s ease-out" },
    },
  },
  plugins: [],
};
