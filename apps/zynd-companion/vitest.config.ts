import { defineConfig } from "vitest/config";

export default defineConfig({
  define: { __API_BASE__: JSON.stringify("https://api.test"), __SITE_BASE__: JSON.stringify("https://cards.test") },
  test: { include: ["test/**/*.test.ts"] },
});
