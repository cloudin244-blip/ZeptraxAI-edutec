import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built into the deployed site folder and served at /portal/ (Vercel project root = zeptrax-learn-flow)
export default defineConfig({
  plugins: [react()],
  base: "/portal/",
  build: {
    outDir: "../Zeptrax_AI_Edutech/zeptrax-learn-flow/portal",
    emptyOutDir: true,
  },
  server: {
    // `npm run dev` talks to the local Python server (python Zeptrax_AI_Edutech/serve_app.py)
    proxy: { "/api": "http://localhost:8000" },
  },
});
