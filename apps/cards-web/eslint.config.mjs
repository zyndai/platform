import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // The dashboard's eslint.config.mjs is missing this, so `eslint` there
    // also lints vendored public/ JS (3rd-party, minified) — 70 errors/
    // 3045 warnings that are noise, not real findings. Excluded here.
    "public/**",
  ]),
]);

export default eslintConfig;
