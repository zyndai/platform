import { PLUGIN_SCOPES } from "./types.js";

/**
 * Chat must never receive or forward a web confirmation nonce.
 * Saving and publication happen only on the signed-in Zynd review page.
 */
export function requireScope(userScopes: string[], scope: string): void {
  if (!userScopes.includes(scope)) throw new Error(`Missing required scope: ${scope}`);
}

export function pluginScopes(scopes: string[]): string[] {
  const granted = new Set(scopes);
  const exact = PLUGIN_SCOPES.filter((scope) => granted.has(scope));
  if (exact.length !== PLUGIN_SCOPES.length || scopes.length !== PLUGIN_SCOPES.length) {
    throw new Error("ZYND ChatGPT plugin token must carry exactly memory:recall memory:propose cards:review");
  }
  return exact;
}
