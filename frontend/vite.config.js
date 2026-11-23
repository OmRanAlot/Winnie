import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api is proxied to the FastAPI backend. scripts/dev-local.ps1 sets
// WINNIE_DEV_API_PROXY when -BackendPort differs from 8000.
const apiProxy = process.env.WINNIE_DEV_API_PROXY || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, open: true, proxy: { "/api": apiProxy } },
});
