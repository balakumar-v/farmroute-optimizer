import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server on :5173. The FastAPI backend allows any origin (CORS *), so the
// app talks to it directly; the URL is configurable in the header's connection chip
// or via VITE_API_BASE at build time.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  build: { chunkSizeWarningLimit: 4000 },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
