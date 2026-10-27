import { ApiError, fetchProfile } from "./api";
import { NOTE_MAX, tidyText } from "./classify";
import { CONNECT_URL, SITE_BASE, STALE_AFTER_DAYS } from "./config";
import { STATE_PATTERN, TOKEN_PATTERN, type GrantProfile } from "./protocol";
import { beginPairing, clearPending, getPending, getStored, setDraft, setPaired } from "./storage";

const MENU_ID = "clip";
const ALARM = "freshness";
const DAY_MS = 86_400_000;

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: MENU_ID, title: "Clip to Zynd profile", contexts: ["page", "link", "selection"] });
  });
  void chrome.alarms.create(ALARM, { periodInMinutes: 360 });
  void refreshBadge();
});
chrome.runtime.onStartup.addListener(() => void refreshBadge());
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM) void refreshBadge();
});

/** A dot on the icon once the card has gone STALE_AFTER_DAYS without a change from here. */
async function refreshBadge(): Promise<void> {
  const { token, touchedAt } = await getStored();
  const stale = Boolean(token && touchedAt && Date.now() - touchedAt > STALE_AFTER_DAYS * DAY_MS);
  await chrome.action.setBadgeText({ text: stale ? "•" : "" });
  if (stale) await chrome.action.setBadgeBackgroundColor({ color: "#d97706" });
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== MENU_ID) return;
  const linked = Boolean(info.linkUrl);
  await setDraft({
    url: info.linkUrl || info.pageUrl || tab?.url || "",
    // The title of a link is not known here; the person fills it in. The page's own title is.
    title: linked ? "" : tab?.title || "",
    note: tidyText(info.selectionText || "", NOTE_MAX),
  });
  try {
    await chrome.action.openPopup();
  } catch {
    // Older browsers cannot open the popup from here: leave a mark on the icon instead.
    await chrome.action.setBadgeText({ text: "+" });
    await chrome.action.setBadgeBackgroundColor({ color: "#5b7cfa" });
  }
});

/** One of this extension's own pages (the popup). A content script's url is the web page it runs in. */
const fromExtensionPage = (sender: chrome.runtime.MessageSender) =>
  sender.id === chrome.runtime.id && (sender.url ?? "").startsWith(chrome.runtime.getURL(""));

/** The Zynd connect page, as seen by the content script: same origin as the website, that one path. */
function fromConnectPage(sender: chrome.runtime.MessageSender): boolean {
  if (sender.id !== chrome.runtime.id || !sender.tab || !sender.url) return false;
  try {
    const url = new URL(sender.url);
    return url.origin === SITE_BASE && url.pathname.replace(/\/$/, "") === new URL(CONNECT_URL).pathname;
  } catch {
    return false;
  }
}

type Message =
  | { type: "pairing:start" }
  | { type: "pairing:state" }
  | { type: "pairing:grant"; state: string; token: string; profile: GrantProfile }
  | { type: "badge:refresh" };

chrome.runtime.onMessage.addListener((message: Message, sender, sendResponse) => {
  void handle(message, sender).then(sendResponse, () => sendResponse({ ok: false, reason: "Something went wrong." }));
  return true; // answered asynchronously
});

async function handle(message: Message, sender: chrome.runtime.MessageSender): Promise<unknown> {
  switch (message?.type) {
    case "pairing:start": {
      if (!fromExtensionPage(sender)) return { ok: false };
      const state = Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");
      await beginPairing(state);
      await chrome.tabs.create({ url: `${CONNECT_URL}?state=${state}` });
      return { ok: true };
    }
    case "pairing:state": {
      if (!fromConnectPage(sender)) return { state: null };
      return { state: (await getPending())?.state ?? null };
    }
    case "pairing:grant":
      return fromConnectPage(sender) ? grant(message) : { ok: false, reason: "Not from the Zynd connect page." };
    case "badge:refresh":
      if (fromExtensionPage(sender)) await refreshBadge();
      return { ok: true };
    default:
      return { ok: false };
  }
}

/** Keep a token only if it is for the pairing this extension started and the API accepts it. */
async function grant(message: Extract<Message, { type: "pairing:grant" }>): Promise<{ ok: boolean; reason?: string }> {
  const pending = await getPending();
  if (!pending || pending.state !== message.state || !STATE_PATTERN.test(message.state)) {
    return { ok: false, reason: "This connection was not started from the extension, or it timed out. Start again from the extension." };
  }
  if (!TOKEN_PATTERN.test(message.token)) return { ok: false, reason: "That was not a valid connection." };
  try {
    const profile = await fetchProfile(message.token);
    await setPaired(message.token, {
      handle: profile.handle,
      name: profile.name,
      headline: profile.headline,
      avatar_url: profile.avatar_url,
      card_url: profile.card_url,
    });
  } catch (error) {
    return { ok: false, reason: error instanceof ApiError ? error.message : "Zynd could not be reached." };
  }
  await clearPending();
  await refreshBadge();
  return { ok: true };
}
