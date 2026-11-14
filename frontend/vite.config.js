import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api/* is forwarded to the FastAPI backend (cd backend && uv run fastapi dev app/main.py).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, open: true, proxy: { "/api": "http://localhost:8000" } },
});
