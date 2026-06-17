import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api → FastAPI (localhost:8000), so the SPA is same-origin
// in dev (no CORS juggling) and works behind one origin in prod.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
