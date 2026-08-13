import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // In development the API is proxied so the browser only ever sees one
    // origin. The Reeve API key lives on the backend and must never be shipped
    // to the client, so there is no direct-to-Reeve path from here by design.
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
