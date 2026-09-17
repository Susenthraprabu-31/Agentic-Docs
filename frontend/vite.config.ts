import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import type { IncomingMessage } from "http";

const API_TARGET = "http://localhost:8000";

/** React routes share prefixes with API paths — serve SPA on browser refresh. */
function spaAwareApiProxy() {
  return {
    target: API_TARGET,
    bypass(req: IncomingMessage) {
      if (req.headers.accept?.includes("text/html")) {
        return "/index.html";
      }
    },
  };
}

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/search": API_TARGET,
      "/runs": spaAwareApiProxy(),
      "/reports": spaAwareApiProxy(),
      "/locations": API_TARGET,
      "/pipeline": API_TARGET,
      "/config": API_TARGET,
      "/ai-agent": API_TARGET,
      "/health": API_TARGET,
      "/batches": spaAwareApiProxy(),
      "/workflows": API_TARGET,
      "/local_storage": API_TARGET,
      "/downloads": API_TARGET,
      "/screenshots": API_TARGET,
    },
  },
});
