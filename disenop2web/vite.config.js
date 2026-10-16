import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vite.dev/config/
// BASE_PATH lets each environment serve the app from a different sub-path
// (e.g. "/" in production, "/test/" in the test environment) without
// needing a different vite.config.js per server.
export default defineConfig({
  base: process.env.BASE_PATH || "/",
  plugins: [react()],
});
