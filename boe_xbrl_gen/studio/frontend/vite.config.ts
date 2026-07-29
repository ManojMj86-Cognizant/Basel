import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite dev server proxies /api -> FastAPI backend on :8200.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8201", changeOrigin: true },
    },
  },
});
