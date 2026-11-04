/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // Matches the main ZeptraAI Edutech site
        background: "#0a0f1c",
        card: "#0f1626",
        border: "#1f2a3d",
        muted: "#8b95a7",
        primary: { DEFAULT: "#3b82f6", hover: "#2563eb" },
        accent: "#06b6d4",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
      },
    },
  },
  plugins: [],
};
