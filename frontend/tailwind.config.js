export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: {
    fontFamily: { sans: ["Geist", "system-ui", "sans-serif"], mono: ["Geist Mono", "ui-monospace", "monospace"] },
    colors: {
      page: "#020202", sunken: "#0b0b0b", raised: "#191817", hover: "#1c1b1a",
      line: "#232120", line2: "#2e2c2b",
      ink: { 1: "#eeeeee", 2: "#d6d3d2", 3: "#a49d9a", 4: "#8a8380", 5: "#5c5855", 6: "#3d3a39" },
      accent: { DEFAULT: "#ef6f2e", 2: "#ee6018", 3: "#d15010" },
    },
    keyframes: { fadein: { from: { opacity: 0, transform: "translateY(3px)" }, to: { opacity: 1, transform: "none" } },
                 shimmer: { "0%": { backgroundPosition: "-200% 0" }, "100%": { backgroundPosition: "200% 0" } } },
    animation: { fadein: "fadein .28s ease-out both", shimmer: "shimmer 2.2s linear infinite" },
  } },
  plugins: [],
}
