import { defineConfig } from "@playwright/test";

/**
 * Smoke tests run against the local dev server with the cards API pointed at a
 * tiny fixture server (tests/fixtures/api-mock.ts) so they never touch the
 * real backend or Supabase.
 */
export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  // Suites share one mutable fixture API (including visitor preferences/counts).
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:3010",
    trace: "retain-on-failure",
  },
  webServer: {
    command:
      "NEXT_PUBLIC_API_URL=http://127.0.0.1:3030 NEXT_PUBLIC_ZYND_API_URL=http://127.0.0.1:3030 NEXT_PUBLIC_MCP_URL=http://127.0.0.1:3030/mcp NEXT_PUBLIC_FEATURE_S12_INTROS=true NEXT_PUBLIC_FEATURE_S10_HOME=true NEXT_PUBLIC_FEATURE_S08_ONBOARDING_V2=true NEXT_PUBLIC_FEATURE_S08_PCT=100 NEXT_PUBLIC_SUPABASE_URL=http://127.0.0.1:3030 NEXT_PUBLIC_SUPABASE_ANON_KEY=smoke-anon-key npm run dev -- -p 3010",
    url: "http://127.0.0.1:3010",
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
  globalSetup: "./tests/fixtures/global-setup.ts",
});
