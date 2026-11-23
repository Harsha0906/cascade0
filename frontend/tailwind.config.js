/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Anastasia Cherniak "Rinesk" Sage & Charcoal Palette
        sage: {
          50: "#f6f8f5",
          100: "#eaf0e8",
          200: "#d6e2d3",
          300: "#b9ccb5",
          400: "#9caea0",
          500: "#899c8d",
          600: "#738677",
          700: "#5c6c60",
          800: "#49564c",
          900: "#3d473f",
        },
        charcoal: {
          50: "#f0f4f1",
          100: "#d9e2db",
          200: "#b5c5b9",
          400: "#6a8170",
          600: "#38473c",
          700: "#27342b",
          800: "#1d2820",
          900: "#152017",
          950: "#0c130d",
        },
        acid: {
          DEFAULT: "#e5f43a",
          hover: "#d5e429",
          active: "#c5d31c",
          text: "#141f16",
        },
        coral: {
          DEFAULT: "#ff4757",
          hover: "#ee3848",
          glow: "rgba(255, 71, 87, 0.45)",
        },
        ground: "#EDF0EB",
        paper: "#FAFBF8",
        rule: "#D9DFD6",
        alert: { DEFAULT: "#B42318", deep: "#8A1A12", soft: "#FBE9E7" },
        forest: {
          DEFAULT: "#1f3a2b",
          light: "#2b4e3a",
          deep: "#14251c",
        },
      },
      fontFamily: {
        display: ["Figtree", "Inter", "-apple-system", "sans-serif"],
        sans: ["Inter", "-apple-system", "BlinkMacSystemFont", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["'JetBrains Mono'", "SFMono-Regular", "Menlo", "Monaco", "Consolas", "monospace"],
      },
      boxShadow: {
        island: "0 20px 45px -15px rgba(21, 32, 23, 0.15), 0 0 0 1px rgba(255, 255, 255, 0.35) inset",
        "island-hover": "0 25px 55px -15px rgba(21, 32, 23, 0.22), 0 0 0 1px rgba(255, 255, 255, 0.5) inset",
        pill: "0 8px 24px -4px rgba(229, 244, 58, 0.45)",
        "pill-coral": "0 8px 24px -4px rgba(255, 71, 87, 0.45)",
        glass: "0 12px 32px 0 rgba(20, 30, 22, 0.12)",
      },
      borderRadius: {
        island: "28px",
        "island-lg": "36px",
      },
    },
  },
  plugins: [],
};
