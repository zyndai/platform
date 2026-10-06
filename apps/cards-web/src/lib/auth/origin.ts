/**
 * Browser-facing origin for OAuth redirects and post-login Location headers.
 *
 * Next may bind to 0.0.0.0 (pm2 HOSTNAME). That is a listen address, not a
 * host the browser or Supabase allowlist can use. Production must never
 * emit localhost / 127.0.0.1 / 0.0.0.0.
 */

const UNSPECIFIED = new Set(["0.0.0.0", "::", "[::]"]);
const LOOPBACK = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);
const PROD_ORIGIN = "https://cards.zynd.ai";

function isProd(): boolean {
  return process.env.NODE_ENV === "production";
}

function hostnameOf(host: string): string {
  return host.replace(/^\[/, "").replace(/\](?::\d+)?$/, "").split(":")[0] ?? host;
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
  const url = parseOrigin(process.env.NEXT_PUBLIC_SITE_URL);
  if (!url || isUnusableHost(url.hostname)) return null;
  return url.origin;
}

function fallbackOrigin(): string {
  if (isProd()) return siteOrigin() ?? PROD_ORIGIN;
  return siteOrigin() ?? "http://localhost:3002";
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

export function requestOrigin(request: {
  url: string;
  headers: { get(name: string): string | null };
}): string {
  const forwardedProto = request.headers.get("x-forwarded-proto")?.split(",")[0]?.trim();
  const forwardedHost = request.headers.get("x-forwarded-host")?.split(",")[0]?.trim();
  const hostHeader = request.headers.get("host");
  const fromUrl = new URL(request.url);

  const host = [forwardedHost, hostHeader, fromUrl.host].find(
    (h) => h && !isUnusableHost(hostnameOf(h)),
  );

  if (!host) return fallbackOrigin();

  const proto =
    forwardedProto === "http" || forwardedProto === "https"
      ? forwardedProto
      : isProd()
        ? "https"
        : fromUrl.protocol.replace(":", "") || "http";

  return canonicalOrigin(`${proto}://${host}`);
}

export function oauthCallbackUrl(): string {
  return `${clientOrigin()}/auth/callback`;
}
