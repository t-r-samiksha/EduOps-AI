/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "1.5rem",
      screens: { "2xl": "1400px" },
    },
    extend: {
      fontFamily: {
        display: ["Montserrat", "sans-serif"],
        sans: ["Roboto", "sans-serif"],
        mono: ["'Roboto Mono'", "monospace"],
      },
      colors: {
        border: "hsl(var(--border))",
        "border-strong": "hsl(var(--border-strong))",
        ring: "hsl(var(--ring))",
        paper: "hsl(var(--paper))",
        panel: "hsl(var(--panel))",
        elevated: "hsl(var(--elevated))",
        ink: {
          DEFAULT: "hsl(var(--ink))",
          muted: "hsl(var(--ink-muted))",
          faint: "hsl(var(--ink-faint))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          hover: "hsl(var(--accent-hover))",
          foreground: "hsl(var(--accent-foreground))",
        },
        urgent: {
          DEFAULT: "hsl(var(--urgent))",
          foreground: "hsl(var(--urgent-foreground))",
        },
        positive: {
          DEFAULT: "hsl(var(--positive))",
          foreground: "hsl(var(--positive-foreground))",
        },
        warning: {
          DEFAULT: "hsl(var(--warning))",
          foreground: "hsl(var(--warning-foreground))",
        },
        // Back-compat: only `muted` is still referenced (stub dashboard pages).
        muted: {
          DEFAULT: "hsl(var(--panel))",
          foreground: "hsl(var(--ink-muted))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        xl: "1rem",
        "2xl": "1.25rem",
        "3xl": "1.75rem",
      },
      fontSize: {
        xs: ["0.75rem", { lineHeight: "1.1rem" }],
        sm: ["0.8125rem", { lineHeight: "1.25rem" }],
        base: ["0.9375rem", { lineHeight: "1.5rem" }],
        lg: ["1.0625rem", { lineHeight: "1.6rem" }],
        xl: ["1.25rem", { lineHeight: "1.7rem" }],
        "2xl": ["1.5rem", { lineHeight: "1.9rem" }],
        "3xl": ["1.875rem", { lineHeight: "2.2rem" }],
      },
      boxShadow: {
        panel: "0 1px 2px 0 hsl(var(--ink) / 0.06)",
        // Real elevation depth, tinted with the theme's own ink hue rather than
        // pure black — the dark side leans on an inset top highlight since cast
        // shadows barely read against an already-dark background.
        elevated: "var(--shadow-elevated)",
        floating: "var(--shadow-floating)",
      },
    },
  },
  plugins: [],
};
