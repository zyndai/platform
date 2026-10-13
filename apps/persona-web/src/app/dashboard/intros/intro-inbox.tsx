"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { authFetch } from "@/lib/api";
import "./intros.css";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
interface Intro {
  id: string; requester_uid: string; requester_name: string; owner_name: string;
  status: string; why: string; asks: string[]; thread_id: string;
  permissions: { can_request_meetings?: boolean }; meeting_task_id: string | null;
}
interface Rule { requester_uid: string; rule: "allow" | "deny" }

async function request<T>(path: string, method = "GET", body?: object): Promise<T> {
  const response = await authFetch(`${API}/api/intros${path}`, {
    method, cache: "no-store", headers: { "Content-Type": "application/json" },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Could not update introductions");
  return result as T;
}

export function IntroInbox() {
  const [rows, setRows] = useState<Intro[] | null>(null);
  const [rules, setRules] = useState<Rule[]>([]);
  const [outgoing, setOutgoing] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    const result = await request<{ intros: Intro[] }>(outgoing ? "?outgoing=true" : "");
    setRows(result.intros);
    const preferences = await request<{ rules: Rule[] }>("/rules/mine");
    setRules(preferences.rules);
    setError("");
  }, [outgoing]);
  useEffect(() => {
    let cancelled = false;
    Promise.all([request<{ intros: Intro[] }>(outgoing ? "?outgoing=true" : ""), request<{ rules: Rule[] }>("/rules/mine")])
      .then(([result, preferences]) => { if (!cancelled) { setRows(result.intros); setRules(preferences.rules); setError(""); } })
      .catch(failure => { if (!cancelled) setError(failure instanceof Error ? failure.message : "Requests unavailable"); });
    return () => { cancelled = true; };
  }, [outgoing]);
  async function respond(id: string, body: object) { await request(`/${id}/respond`, "POST", body); await load(); }
  async function older() {
    try {
      const result = await request<{ intros: Intro[] }>(`${outgoing ? "?outgoing=true&" : "?"}offset=${rows?.length || 0}`);
      setRows(current => [...(current || []), ...result.intros.filter(row => !current?.some(item => item.id === row.id))]);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Could not load older requests"); }
  }
  async function rule(uid: string, value: "allow" | "deny" | "remove") {
    try {
      if (value === "remove") await request(`/rules/mine/${uid}`, "DELETE");
      else await request("/rules/mine", "PUT", { requester_uid: uid, rule: value });
      await load();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Could not update preferences"); }
  }
  return <main className="persona-intros" style={{ maxWidth: 900, padding: 24, margin: "auto" }}>
    <h1>Introductions</h1>
    <p>You decide who may connect and whether to arrange a call.</p>
    <button onClick={() => { setRows(null); setOutgoing(!outgoing); }}>{outgoing ? "Received requests" : "Sent requests"}</button>{" "}
    <button onClick={() => void load().catch(failure => setError(failure.message))}>Refresh</button>
    <p role="alert">{error}</p>
    {!rows ? <p>Loading requests…</p> : rows.length === 0 ? <p>No intro requests yet.</p> : rows.map(row =>
      <IntroItem key={row.id} row={row} outgoing={outgoing} respond={respond} rule={rule} />)}
    {rows && rows.length > 0 && rows.length % 100 === 0 && <button onClick={() => void older()}>Load older requests</button>}
    <details><summary>Who can request an intro?</summary>
      <p>Blocked people cannot request intros. If you add anyone to your allow list,
        only people on that list can request intros. Allow-list entries still require your approval.</p>
      {rules.length === 0 ? <p>No allow-list or block rules.</p> : rules.map(entry => <p key={entry.requester_uid}>
        {rows?.find(row => row.requester_uid === entry.requester_uid)?.requester_name || "Linked Persona account"}: {entry.rule}
        {" "}<button onClick={() => void rule(entry.requester_uid, "remove")}>Remove rule</button>
      </p>)}
    </details>
  </main>;
}

function IntroItem({ row, outgoing, respond, rule }: {
  row: Intro; outgoing: boolean; respond: (id: string, body: object) => Promise<void>;
  rule: (uid: string, value: "allow" | "deny" | "remove") => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [grant, setGrant] = useState(false);
  const [start, setStart] = useState("");
  const [error, setError] = useState("");
  async function decide(action: string) {
    setBusy(true);
    setError("");
    try {
      const body: Record<string, unknown> = { action, allow_meetings: action === "accept" && grant };
      if (start && (action === "accept" || action === "propose_time")) {
        const date = new Date(start);
        body.start_time = date.toISOString();
        body.end_time = new Date(date.getTime() + 20 * 60_000).toISOString();
      }
      await respond(row.id, body);
      setStart("");
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Could not update request"); }
    finally { setBusy(false); }
  }
  return <article style={{ borderTop: "1px solid #ddd", margin: "24px 0", paddingTop: 16 }}>
    <h2>{outgoing ? `To ${row.owner_name}` : `From ${row.requester_name}`} · {row.status}</h2>
    <p style={{ whiteSpace: "pre-wrap" }}>{row.why}</p>
    <p>Asked for {row.asks.includes("meeting") ? "an intro and a call" : "an intro"}.</p>
    {!outgoing && row.status === "pending" && <>
      {row.asks.includes("meeting") && <label><input type="checkbox" checked={grant} onChange={e => setGrant(e.target.checked)} disabled={busy} /> Allow coordinating a call</label>}
      {grant && <label style={{ display: "block" }}>Optional 20-minute call proposal (your local time)
        <input type="datetime-local" value={start} onChange={e => setStart(e.target.value)} disabled={busy} /></label>}
      <p><button disabled={busy} onClick={() => void decide("accept")}>Accept intro</button>{" "}
        <button disabled={busy} onClick={() => void decide("decline")}>Decline</button>{" "}
        <button disabled={busy} onClick={() => void decide("block")}>Block requester</button></p>
    </>}
    {!outgoing && row.status === "accepted" && row.permissions.can_request_meetings && !row.meeting_task_id && <label>
      Propose a 20-minute call (your local time) <input type="datetime-local" value={start} onChange={e => setStart(e.target.value)} disabled={busy} />
      <button disabled={busy || !start} onClick={() => void decide("propose_time")}>Propose time</button>
    </label>}
    {row.status === "accepted" && <p>{row.meeting_task_id ? "Meeting proposed; confirm it in your conversation." : "Connected. No meeting booked."}
      {" "}<Link href={`/dashboard/messages?thread=${row.thread_id}`}>Open conversation →</Link></p>}
    {!outgoing && <p><button disabled={busy} onClick={() => void rule(row.requester_uid, "allow")}>Add to allow list</button>{" "}
      <button disabled={busy} onClick={() => void rule(row.requester_uid, "deny")}>Deny future requests</button></p>}
    <p role="alert">{error}</p>
  </article>;
}
