// Builds the extension into dist/. `--dev` points it at a local Cards API and website.
//   npm run build        production addresses (api.zynd.ai, cards.zynd.ai)
//   npm run build:dev    http://localhost:8002 and http://localhost:3002 (docs/LOCAL_DEV.md)
import { build } from "esbuild";
import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const dev = process.argv.includes("--dev");
const flag = (name) => {
  const at = process.argv.indexOf(name);
  return at > 0 ? process.argv[at + 1] : undefined;
};

const API = flag("--api") ?? (dev ? "http://localhost:8002" : "https://api.zynd.ai");
const SITE = flag("--site") ?? (dev ? "http://localhost:3002" : "https://cards.zynd.ai");
const dist = join(root, flag("--out") ?? "dist");

await rm(dist, { recursive: true, force: true });
await mkdir(dist, { recursive: true });

// No minify and no keepNames: readPage() is serialised into other pages by Chrome and must stay
// self-contained. The code is small and the store reviews readable source.
await build({
  absWorkingDir: root,
  entryPoints: {
    background: "src/background.ts",
    "connect-bridge": "src/connect-bridge.ts",
    popup: "src/popup/popup.ts",
  },
  outdir: dist,
  bundle: true,
  format: "iife",
  target: "chrome110",
  define: { __API_BASE__: JSON.stringify(API), __SITE_BASE__: JSON.stringify(SITE) },
  legalComments: "none",
  logLevel: "warning",
});

await cp(join(root, "src/popup/popup.html"), join(dist, "popup.html"));
await cp(join(root, "src/popup/popup.css"), join(dist, "popup.css"));
await cp(join(root, "icons"), join(dist, "icons"), { recursive: true });

const manifest = JSON.parse(await readFile(join(root, "manifest.json"), "utf8"));
const pkg = JSON.parse(await readFile(join(root, "package.json"), "utf8"));
manifest.version = pkg.version;
manifest.host_permissions = [`${API}/*`];
// End-to-end tests only (npm run test:e2e): automation cannot click the toolbar icon, which is what
// grants activeTab, so the test build is given plain access to the pages it opens instead.
const testHost = flag("--test-host");
if (testHost) manifest.host_permissions.push(...testHost.split(","));
manifest.content_scripts[0].matches = [`${SITE}/companion/connect*`];
if (dev) {
  manifest.name = "Zynd Companion (dev)";
  // localhost and 127.0.0.1 are different origins to a browser; the dev site may be opened as either.
  const alias = SITE.replace("//localhost", "//127.0.0.1");
  if (alias !== SITE) manifest.content_scripts[0].matches.push(`${alias}/companion/connect*`);
}
await writeFile(join(dist, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
console.log(`zynd-companion ${manifest.version} -> ${dist}\n  api  ${API}\n  site ${SITE}`);
