/**
 * The extension's only content script. It is matched to the Zynd connect page and nowhere else.
 * It lets that page and the extension agree on a pairing: the page asks who is there, the
 * extension says which pairing it is waiting for, and after the person confirms on the page the
 * page hands over a device token. The background worker, not this script, decides whether to keep it.
 */
import { FROM_EXTENSION, readPageMessage, type ExtensionMessage } from "./protocol";

const say = (message: ExtensionMessage) => window.postMessage(message, window.location.origin);

async function announce(): Promise<void> {
  const reply = (await chrome.runtime.sendMessage({ type: "pairing:state" })) as { state: string | null } | undefined;
  say({ source: FROM_EXTENSION, type: "ready", state: reply?.state ?? null });
}

window.addEventListener("message", (event: MessageEvent) => {
  // Only this page, talking to itself. A frame or another window cannot start or finish a pairing.
  if (event.source !== window || event.origin !== window.location.origin) return;
  const message = readPageMessage(event.data);
  if (!message) return;
  if (message.type === "hello") {
    void announce();
    return;
  }
  void chrome.runtime
    .sendMessage({ type: "pairing:grant", state: message.state, token: message.token, profile: message.profile })
    .then((reply: { ok: boolean; reason?: string } | undefined) => {
      say(reply?.ok
        ? { source: FROM_EXTENSION, type: "paired", state: message.state }
        : { source: FROM_EXTENSION, type: "rejected", state: message.state, reason: reply?.reason || "The extension did not accept the connection." });
    })
    .catch(() => say({ source: FROM_EXTENSION, type: "rejected", state: message.state, reason: "The extension could not be reached." }));
});

void announce();
