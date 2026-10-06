import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The product name lives in one place (../app.config.json), shared with the backend.
const appConfig = JSON.parse(readFileSync(new URL("../app.config.json", import.meta.url), "utf-8"));
const backend = process.env.DAYLINE_BACKEND ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: { __APP_NAME__: JSON.stringify(appConfig.name) },
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    host: true, // reachable from phones on the same Wi-Fi/hotspot
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: false },
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
});
