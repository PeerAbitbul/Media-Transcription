import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built assets are served from the FastAPI app at "/". During local dev the
// proxy forwards /api to the running backend on :8000.
export default defineConfig({
  base: "/",
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    proxy: { "/api": "http://localhost:8000" },
  },
});
