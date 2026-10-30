import {
  ApiError, addExploring, addWorkingOn, confirmWorkingOn, disconnect, fetchProfile, removeExploring, removeWorkingOn,
  type ExploringItem, type Lists, type Profile,
} from "../api";
import {
  KINDS, NOTE_MAX, TITLE_MAX, WORKING_ON_MAX, cleanUrl, detectKind, tidyText, tidyTitle, type Kind,
} from "../classify";
import { STALE_AFTER_DAYS } from "../config";
import { readPage, type PageInfo } from "../page-info";
import { clearPaired, getStored, takeDraft, touch, updateAccount, type Account } from "../storage";

const app = document.getElementById("app") as HTMLElement;
const DAY_MS = 86_400_000;

type Attrs = Record<string, string | boolean | ((event: Event) => void) | undefined>;

/** Tiny DOM builder. Text always goes in as text, never as markup: titles and notes come from web pages. */
function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Attrs = {}, ...children: (Node | string | null | false)[]): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === false) continue;
    if (typeof value === "function") el.addEventListener(key.replace(/^on/, ""), value);
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, value);
  }
  for (const child of children) if (child) el.append(child);
  return el;
}

/** Links in this window come from the server; only ever draw web links. */
const safeHref = (url: string): string => (/^https?:\/\//i.test(url) ? url : "#");

function render(...nodes: (Node | null)[]): void {
  app.replaceChildren(...nodes.filter((node): node is Node => node !== null));
}

function status(): { say(text: string, error?: boolean): void; node: HTMLElement } {
  const node = h("p", { class: "status", role: "status" });
  return {
    node,
    say(text, error = false) {
      node.textContent = text;
      node.className = error ? "status error" : "status";
    },
  };
}

// ── Not connected ───────────────────────────────────────────────────────────

function renderConnect(note = ""): void {
  const line = status();
  if (note) line.say(note, true);
  render(
    h("div", { class: "center" },
      h("h1", {}, "Zynd Companion"),
      h("p", {}, "Update your Zynd card from the page you are on. Connect it to your account first."),
      h("button", {
        class: "primary",
        onclick: async () => {
          await chrome.runtime.sendMessage({ type: "pairing:start" });
          window.close();
        },
      }, "Connect Zynd account"),
    ),
    line.node,
  );
}

// ── Connected ───────────────────────────────────────────────────────────────

interface Clippable {
  url: string;
  title: string;
  note: string;
  kind: Kind;
}

type Candidate = { ok: true; clip: Clippable } | { ok: false; reason: string };

function candidateFrom(rawUrl: string, fallbackTitle: string, note: string, hints: Partial<PageInfo>): Candidate {
  const checked = cleanUrl(rawUrl);
  if (!checked.ok) return checked;
  return {
    ok: true,
    clip: {
      // What the page calls itself (og:title) is usually cleaner than the tab's title.
      url: checked.url,
      title: tidyTitle(hints.title || fallbackTitle, checked.url),
      note: tidyText(note || hints.selection || "", NOTE_MAX),
      kind: detectKind(checked.url, hints),
    },
  };
}

/** What to offer: a clip started from the right-click menu, else the tab the person is on. */
async function currentCandidate(): Promise<Candidate> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const draft = await takeDraft();
  let hints: Partial<PageInfo> = {};
  if (tab?.id !== undefined) {
    try {
      const [result] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: readPage });
      hints = (result?.result as PageInfo | undefined) ?? {};
    } catch {
      // Pages the browser keeps to itself (the Web Store, about: pages): the tab's own title will do.
    }
  }
  if (draft) return candidateFrom(draft.url, draft.title, draft.note, draft.url === tab?.url ? hints : { title: draft.title });
  if (!tab?.url) return { ok: false, reason: "There is no page to add." };
  return candidateFrom(tab.url, tab.title || "", "", hints);
}

function chipList(items: string[], onRemove: (item: string) => void, label: string): HTMLElement {
  return h("ul", { class: "chips", "aria-label": label },
    ...items.map((item) => h("li", { class: "chip" },
      h("span", { title: item }, item),
      h("button", { type: "button", "aria-label": `Remove ${item}`, onclick: () => onRemove(item) }, "×"),
    )),
  );
}

function clipList(items: ExploringItem[], onRemove: (item: ExploringItem) => void): HTMLElement | null {
  if (items.length === 0) return null;
  return h("ul", { class: "clips", "aria-label": "Recently added" },
    ...items.slice(0, 5).map((item) => h("li", {},
      h("span", { class: "tag" }, item.kind),
      h("a", { href: safeHref(item.url), target: "_blank", rel: "noopener noreferrer", title: item.url }, item.title || item.url),
      h("button", { type: "button", class: "x", "aria-label": `Remove ${item.title || item.url}`, onclick: () => onRemove(item) }, "×"),
    )),
  );
}

async function renderMain(): Promise<void> {
  const stored = await getStored();
  if (!stored.token || !stored.account) return renderConnect();
  let account: Account = stored.account;
  let lists: Lists = { working_on: [], exploring: [] };
  const candidate = await currentCandidate();
  const line = status();

  // Re-drawn after every change so the lists always show what the API says is saved.
  function draw(): void {
    const workingInput = h("input", { type: "text", maxlength: String(WORKING_ON_MAX), placeholder: "What are you working on?", "aria-label": "Working on" });
    const workingAdd = h("button", { type: "button", class: "primary" }, "Add");
    const submitWorking = () => void changeLists(async () => {
      const text = tidyText(workingInput.value, WORKING_ON_MAX);
      if (!text) return null;
      return addWorkingOn(text);
    }, "Added to Working on");
    workingAdd.addEventListener("click", submitWorking);
    workingInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") submitWorking();
    });

    const stale = stored.touchedAt !== undefined && Date.now() - stored.touchedAt > STALE_AFTER_DAYS * DAY_MS;
    const banner = stale
      ? h("div", { class: "banner" },
          "It has been a while since you updated your card. Still working on this?",
          h("div", { class: "row" },
            h("button", { type: "button", onclick: () => void keepWorkingOn() }, "Yes, keep it"),
            h("button", { type: "button", onclick: () => workingInput.focus() }, "Update"),
          ))
      : null;

    render(
      h("div", { class: "who" },
        account.avatar_url ? h("img", { class: "avatar", src: account.avatar_url, alt: "", referrerpolicy: "no-referrer" }) : h("div", { class: "avatar" }),
        h("div", {},
          h("div", { class: "who-name" }, account.name || account.handle),
          h("div", { class: "who-sub" }, h("a", { href: safeHref(account.card_url), target: "_blank", rel: "noopener noreferrer" }, account.card_url.replace(/^https?:\/\//, ""))),
        ),
      ),
      banner,
      h("section", {},
        h("h2", {}, "Working on"),
        h("div", { class: "row" }, workingInput, workingAdd),
        chipList(lists.working_on, (item) => void changeLists(() => removeWorkingOn(item), "Removed"), "Your working on lines"),
      ),
      h("section", {}, h("h2", {}, "Currently exploring"), clipForm(candidate), clipList(lists.exploring, (item) => void changeLists(() => removeExploring(item.url), "Removed"))),
      line.node,
      h("footer", {},
        h("a", { href: safeHref(account.card_url), target: "_blank", rel: "noopener noreferrer" }, "View my card"),
        h("button", { type: "button", class: "link", onclick: () => void signOut() }, "Disconnect"),
      ),
    );
  }

  function clipForm(found: Candidate): Node {
    if (!found.ok) return h("p", { class: "hint" }, found.reason);
    let kind = found.clip.kind;
    const title = h("input", { type: "text", maxlength: String(TITLE_MAX), value: found.clip.title, "aria-label": "Title" });
    const note = h("textarea", { maxlength: String(NOTE_MAX), placeholder: "Add a note (optional)", "aria-label": "Note" });
    note.value = found.clip.note;
    const add = h("button", { type: "button", class: "primary" }, "Add to my card");
    const kinds = h("div", { class: "kinds", role: "group", "aria-label": "Kind" });
    const drawKinds = () => kinds.replaceChildren(...KINDS.map(({ kind: k, label }) =>
      h("button", { type: "button", "aria-pressed": String(k === kind), onclick: () => { kind = k; drawKinds(); } }, label)));
    drawKinds();
    add.addEventListener("click", () => void changeLists(() => addExploring({
      url: found.clip.url, title: tidyText(title.value, TITLE_MAX), kind, note: tidyText(note.value, NOTE_MAX),
    }), "Added to Currently exploring. It is on your card now."));
    // The whole address, query included: whatever is in it goes on a public card, so the person sees it all.
    return h("div", {},
      title, kinds, note,
      h("p", { class: "addr" }, `Public link: ${found.clip.url}`),
      h("div", { class: "row", style: "margin-top:8px;justify-content:flex-end" }, add),
    );
  }

  async function changeLists(action: () => Promise<Lists | null>, done: string): Promise<void> {
    line.say("Saving…");
    try {
      const next = await action();
      if (!next) return line.say("");
      lists = next;
      stored.touchedAt = Date.now();
      await touch();
      void chrome.runtime.sendMessage({ type: "badge:refresh" });
      draw();
      line.say(done);
    } catch (error) {
      if (error instanceof ApiError && error.unpaired) return renderConnect(error.message);
      line.say(error instanceof Error ? error.message : "That did not work.", true);
    }
  }

  /** The local reminder resets whatever happens; the card's own freshness only where the server can
   *  record it (404 from a server without the route, 503 before migration 0033). */
  async function keepWorkingOn(): Promise<void> {
    stored.touchedAt = Date.now();
    await touch();
    void chrome.runtime.sendMessage({ type: "badge:refresh" });
    draw();
    try {
      await confirmWorkingOn();
      line.say("Thanks. Your card shows Working on as current.");
    } catch (error) {
      if (error instanceof ApiError && error.unpaired) return renderConnect(error.message);
      if (error instanceof ApiError && (error.status === 404 || error.status === 503)) return;
      line.say(error instanceof Error ? error.message : "That did not work.", true);
    }
  }

  async function signOut(): Promise<void> {
    try {
      await disconnect();
    } catch {
      // Offline or already revoked: this browser lets go either way. The website can revoke it later.
    }
    await clearPaired();
    void chrome.runtime.sendMessage({ type: "badge:refresh" });
    renderConnect();
  }

  draw();
  line.say("Loading…");
  try {
    const profile: Profile = await fetchProfile();
    account = { handle: profile.handle, name: profile.name, headline: profile.headline, avatar_url: profile.avatar_url, card_url: profile.card_url };
    await updateAccount(account);
    lists = { working_on: profile.working_on, exploring: profile.exploring };
    draw();
    line.say(profile.published ? "" : "Your card is private, so these will not show until you make it public.");
  } catch (error) {
    if (error instanceof ApiError && error.unpaired) return renderConnect(error.message);
    line.say(error instanceof Error ? error.message : "Could not load your card.", true);
  }
}

void renderMain();
