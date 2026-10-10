import type { FullConfig } from "@playwright/test";
import { startFixtureServer } from "./api-mock";

export default async function globalSetup(_config: FullConfig) {
  void _config;
  await startFixtureServer();
}