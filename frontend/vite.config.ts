import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import type { IncomingMessage } from "http";

const API_TARGET = "http://localhost:8000";

/** Always proxy document file/metadata endpoints to the backend (never the SPA). */
const apiProxy = {
  target: API_TARGET,
  changeOrigin: true,
};

/** React routes share prefixes with API paths — serve SPA on browser refresh. */
function spaAwareApiProxy() {
  return {
    target: API_TARGET,
    changeOrigin: true,
    bypass(req: IncomingMessage) {
      const url = req.url || "";
      // Document APIs must never be routed to the React app.
      if (url.startsWith("/reports/documents")) {
        return null;
      }
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
      "/search": apiProxy,
      "/reports/documents": apiProxy,
      "/runs": spaAwareApiProxy(),
      "/reports": spaAwareApiProxy(),
      "/locations": apiProxy,
      "/pipeline": apiProxy,
      "/config": apiProxy,
      "/ai-agent": apiProxy,
      "/health": apiProxy,
      "/batches": spaAwareApiProxy(),
      "/workflows": apiProxy,
      "/local_storage": apiProxy,
      "/downloads": apiProxy,
      "/screenshots": apiProxy,
    },
  },
});
