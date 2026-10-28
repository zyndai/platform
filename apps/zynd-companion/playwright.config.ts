import { defineConfig } from "@playwright/test";

// Loads the built extension (dist-e2e, see "test:e2e") into a real Chromium and drives it against
// a mock Cards API. Extensions need Chromium's new headless mode, not the headless shell.
export default defineConfig({
  testDir: "test/e2e",
  testMatch: "*.e2e.ts",
  timeout: 60_000,
  workers: 1,
  reporter: "list",
  use: { channel: "chromium" },
});
