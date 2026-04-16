import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          base: "var(--bg-base)",
          surface: "var(--bg-surface)",
          elevated: "var(--bg-elevated)",
          hover: "var(--bg-hover)",
        },
        edge: {
          DEFAULT: "var(--border)",
          soft: "var(--border-soft)",
        },
        text: {
          primary: "var(--text-primary)",
          secondary: "var(--text-secondary)",
          tertiary: "var(--text-tertiary)",
          mono: "var(--text-mono)",
        },
        accent: {
          green: "var(--green)",
          red: "var(--red)",
          blue: "var(--blue)",
          gold: "var(--gold)",
          purple: "var(--purple)",
          cyan: "var(--cyan)",
        },
      },
      fontFamily: {
        sans: ["var(--font-body)"],
        mono: ["var(--font-mono)"],
      },
      maxWidth: {
        content: "1280px",
      },
    },
  },
  plugins: [],
};

export default config;
