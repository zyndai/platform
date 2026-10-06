const UNSPECIFIED = new Set(["0.0.0.0", "::", "[::]"]);
const LOOPBACK = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);
const PROD_ORIGIN = "https://persona.zynd.ai";

function isProd(): boolean {
  return process.env.NODE_ENV === "production";
}

function isUnusableHost(hostname: string): boolean {
  if (UNSPECIFIED.has(hostname)) return true;
  if (isProd() && (LOOPBACK.has(hostname) || hostname.endsWith(".localhost"))) return true;
  return false;
}

function parseOrigin(raw: string | undefined | null): URL | null {
  if (!raw) return null;
  try {
    return new URL(raw.includes("://") ? raw : `http://${raw}`);
  } catch {
    return null;
  }
}

function siteOrigin(): string | null {
  const url = parseOrigin(process.env.NEXT_PUBLIC_PAGE_BASE_URL);
  if (!url || isUnusableHost(url.hostname)) return null;
  return url.origin;
}

function fallbackOrigin(): string {
  if (isProd()) return siteOrigin() ?? PROD_ORIGIN;
  return siteOrigin() ?? "http://localhost:3000";
}

export function canonicalOrigin(raw: string): string {
  const url = parseOrigin(raw);
  if (!url || isUnusableHost(url.hostname)) return fallbackOrigin();
  return url.origin;
}

export function clientOrigin(): string {
  if (typeof window === "undefined") return fallbackOrigin();
  return canonicalOrigin(window.location.origin);
}
