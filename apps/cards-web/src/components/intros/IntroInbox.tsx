"use client";

import { useState } from "react";
import Link from "next/link";
import { ownerRequest } from "@/lib/owner-home";
import type { Intro } from "@/lib/intros";
import "./intros.css";

export function IntroInbox({ initial, token, outgoing = false }: { initial: Intro[] | null; token: string; outgoing?: boolean }) {
  const [rows, setRows] = useState(initial);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function refresh() {
    setBusy(true);
    try {
      const result = await ownerRequest<{ intros: Intro[] }>(`mine/intros${outgoing ? "?outgoing=true" : ""}`, token);
      setRows(result.intros);
      setError("");
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Requests unavailable"); }
    finally { setBusy(false); }
  }
  async function respond(id: string, body: object) {
    await ownerRequest(`mine/intros/${id}/respond`, token, "POST", body);
    await refresh();
  }
  async function older() {
    setBusy(true);
    try {
      const query = `${outgoing ? "?outgoing=true&" : "?"}offset=${rows?.length || 0}`;
      const result = await ownerRequest<{ intros: Intro[] }>("mine/intros" + query, token);
      setRows(current => [...(current || []), ...result.intros.filter(row => !current?.some(item => item.id === row.id))]);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Could not load older requests"); }
    finally { setBusy(false); }
  }
  return <section className="intro-panel" id="intros" style={{ margin: "24px 0" }}>
    <h2>{outgoing ? "Sent intro requests" : "Intro requests"}</h2>
    <p>The receiving owner controls the connection and permission to arrange a call.</p>
    <button type="button" onClick={() => void refresh()} disabled={busy}>Refresh requests</button>{" "}
    <Link href={outgoing ? "/intros" : "/intros?outgoing=true"}>{outgoing ? "Received requests" : "Sent requests"}</Link>
    <p role="alert">{error}</p>
    {rows === null ? <p>Intro requests are temporarily unavailable.</p> : rows.length === 0 ? <p>No intro requests yet.</p> :
      rows.map(row => <IntroItem key={row.id} row={row} outgoing={outgoing} respond={respond} />)}
    {rows && rows.length > 0 && rows.length % 100 === 0 && <button disabled={busy} onClick={() => void older()}>Load older requests</button>}
  </section>;
}

function IntroItem({ row, outgoing, respond }: { row: Intro; outgoing: boolean; respond: (id: string, body: object) => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [grant, setGrant] = useState(false);
  const [start, setStart] = useState("");
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
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Could not update this request"); }
    finally { setBusy(false); }
  }
  const mayPropose = row.status === "accepted" && row.permissions.can_request_meetings && !row.meeting_task_id;
  return <article style={{ borderTop: "1px solid #ddd", marginTop: 16, paddingTop: 16 }}>
    <h3>{outgoing ? `To ${row.owner_name}` : `From ${row.requester_name}`} · {row.status}</h3>
    <p style={{ whiteSpace: "pre-wrap" }}>{row.why}</p>
    <p>Asked for: {row.asks.includes("meeting") ? "an introduction and a call" : "an introduction"}</p>
    {row.status === "accepted" && <p>{row.meeting_task_id ? "Meeting proposed; confirm it in Persona." : "Connected. No meeting booked."}</p>}
    {!outgoing && row.status === "pending" && <>
      {row.asks.includes("meeting") && <label><input type="checkbox" checked={grant} disabled={busy} onChange={e => setGrant(e.target.checked)} /> Allow coordinating a call</label>}
      {grant && <label style={{ display: "block" }}>Optional 20-minute call proposal (your local time)
        <input type="datetime-local" value={start} onChange={e => setStart(e.target.value)} disabled={busy} /></label>}
      <div><button disabled={busy} onClick={() => void decide("accept")}>Accept intro</button>{" "}
        <button disabled={busy} onClick={() => void decide("decline")}>Decline</button>{" "}
        <button disabled={busy} onClick={() => void decide("block")}>Block requester</button></div>
    </>}
    {!outgoing && mayPropose && <label>Propose a 20-minute call (your local time)
      <input type="datetime-local" value={start} onChange={e => setStart(e.target.value)} disabled={busy} />
      <button disabled={busy || !start} onClick={() => void decide("propose_time")}>Propose time</button></label>}
    {row.status === "accepted" && <p><a href={row.conversation_url}>Continue in Persona →</a></p>}
    <p role="alert">{error}</p>
  </article>;
}
