import http from "node:http";

export const PORT = 4777;
export const ORIGIN = `http://127.0.0.1:${PORT}`;
export const WEBSITE_SESSION = "website-session";

const CONNECT_PAGE = `<!doctype html><meta charset="utf-8"><title>connect</title>
<p id="s">searching</p><button id="b" disabled>Connect</button>
<script>
const state = new URLSearchParams(location.search).get("state") || "";
const s = document.getElementById("s"), b = document.getElementById("b");
const say = (text) => (s.textContent = text);
addEventListener("message", (e) => {
  if (e.source !== window || e.origin !== location.origin) return;
  const d = e.data;
  if (!d || d.source !== "zynd-companion" || d.state !== state) return;
  if (d.type === "ready") { say("ready"); b.disabled = false; }
  if (d.type === "paired") say("paired");
  if (d.type === "rejected") say("rejected: " + d.reason);
});
const post = (m) => postMessage(Object.assign({ source: "zynd-cards" }, m), location.origin);
post({ type: "hello" });
b.onclick = async () => {
  const r = await fetch("/cards/companion/pair", { method: "POST", headers: { Authorization: "Bearer ${WEBSITE_SESSION}", "Content-Type": "application/json" }, body: '{"label":"Chrome on Test"}' });
  const j = await r.json();
  post({ type: "grant", state, token: j.token, profile: j.profile });
};
window.forge = (token) => post({ type: "grant", state, token, profile: { handle: "dil", name: "Dil", card_url: "x" } });
</script>`;

/** The pieces of the Cards API the extension talks to, kept in memory. */
export function startMock() {
  const db = { workingOn: [] as string[], exploring: [] as Record<string, string>[], tokens: new Set<string>(), requests: [] as string[], confirmStatus: 200 };
  const profile = () => ({
    handle: "dil", name: "Dil Asrafi", headline: "Builder", avatar_url: "", card_url: "https://cards.zynd.ai/p/dil", published: true,
    working_on: db.workingOn, exploring: db.exploring,
  });
  const lists = () => ({ working_on: db.workingOn, exploring: db.exploring });

  const server = http.createServer((req, res) => {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", () => {
      const url = new URL(req.url ?? "/", ORIGIN);
      const json = (status: number, body?: unknown) => {
        res.writeHead(status, { "Content-Type": "application/json" });
        res.end(body === undefined ? "" : JSON.stringify(body));
      };
      if (url.pathname === "/companion/connect") {
        res.writeHead(200, { "Content-Type": "text/html" });
        return res.end(CONNECT_PAGE);
      }
      const route = url.pathname.replace("/cards/companion", "");
      db.requests.push(`${req.method} ${route}`);
      const auth = req.headers.authorization ?? "";
      if (route === "/pair" && req.method === "POST") {
        if (auth !== `Bearer ${WEBSITE_SESSION}`) return json(401, { detail: "Unauthorized" });
        const token = `zdc_${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}abcdefghij`;
        db.tokens.add(token);
        return json(200, { token, device: { id: "d1", label: "Chrome on Test" }, profile: profile() });
      }
      const token = auth.replace(/^Bearer /, "");
      if (!db.tokens.has(token)) return json(401, { detail: "Unauthorized" });
      const body = raw ? JSON.parse(raw) : {};
      if (route === "/me") return json(200, profile());
      if (route === "/working-on") db.workingOn = [body.text, ...db.workingOn.filter((t) => t !== body.text)];
      else if (route === "/working-on/remove") db.workingOn = db.workingOn.filter((t) => t !== body.text);
      else if (route === "/exploring") db.exploring = [{ ...body, added_at: new Date().toISOString() }, ...db.exploring.filter((i) => i.url !== body.url)];
      else if (route === "/exploring/remove") db.exploring = db.exploring.filter((i) => i.url !== body.url);
      else if (route === "/working-on/confirm") {
        return db.confirmStatus === 200
          ? json(200, { working_on_updated_at: new Date().toISOString() })
          : json(db.confirmStatus, { detail: "Confirming isn't available yet" });
      }
      else if (route === "/disconnect") { db.tokens.delete(token); return json(204); }
      else return json(404, { detail: "not found" });
      return json(200, lists());
    });
  });
  return {
    db,
    listen: () => new Promise<void>((ok) => server.listen(PORT, "127.0.0.1", ok)),
    close: () => new Promise<void>((ok) => server.close(() => ok())),
  };
}
