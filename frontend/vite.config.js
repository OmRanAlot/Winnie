import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api is proxied to the FastAPI backend (uv run fastapi dev app/main.py, port 8000).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, open: true, proxy: { "/api": "http://localhost:8000" } },
});
