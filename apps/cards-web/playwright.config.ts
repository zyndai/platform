import { defineConfig } from "@playwright/test";

/**
 * Smoke tests run against the local dev server with the cards API pointed at a
 * tiny fixture server (tests/fixtures/api-mock.ts) so they never touch the
 * real backend or Supabase.
 */
export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  fullyParallel: true,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:3010",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "NEXT_PUBLIC_API_URL=http://127.0.0.1:3030 npm run dev -- -p 3010",
    url: "http://127.0.0.1:3010",
    reuseExistingServer: true,
    timeout: 180_000,
  },
  globalSetup: "./tests/fixtures/global-setup.ts",
});