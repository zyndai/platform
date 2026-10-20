"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, MessageCircle, Plus, Search, Send, Users, X } from "lucide-react";
import {
  cardsNetworkRequest,
  connectionRequestNotice,
  markNetworkRead,
  type CardConnection,
  type CardGroup,
  type CardGroupInvitation,
  type CardGroupMember,
  type CardMessage,
  type CardSummary,
} from "@/lib/cards-network";

type Tab = "connections" | "groups";

const panelStyle: React.CSSProperties = {
  border: "1px solid rgba(255,255,255,.1)",
  background: "rgba(14,18,30,.78)",
  borderRadius: 18,
  padding: 22,
};

function Avatar({ card }: { card?: CardSummary | null }) {
  return card?.avatar_url ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={card.avatar_url} alt="" style={{ width: 40, height: 40, borderRadius: "50%", objectFit: "cover" }} />
  ) : (
    <span style={{ width: 40, height: 40, borderRadius: "50%", display: "grid", placeItems: "center", background: "#6366f1", color: "white", fontWeight: 800 }}>
      {(card?.name || "?").slice(0, 1).toUpperCase()}
    </span>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p style={{ color: "#9ca3af", lineHeight: 1.6, margin: "12px 0 0" }}>{children}</p>;
}

export function NetworkClient({ token, userId }: { token: string; userId: string }) {
  const [tab, setTab] = useState<Tab>("connections");
  const [connections, setConnections] = useState<CardConnection[]>([]);
  const [groups, setGroups] = useState<CardGroup[]>([]);
  const [invitations, setInvitations] = useState<CardGroupInvitation[]>([]);
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [groupId, setGroupId] = useState<string | null>(null);
  const [messages, setMessages] = useState<CardMessage[]>([]);
  const [groupMessages, setGroupMessages] = useState<CardMessage[]>([]);
  const [members, setMembers] = useState<CardGroupMember[]>([]);
  const [draft, setDraft] = useState("");
  const [groupDraft, setGroupDraft] = useState("");
  const [targetHandle, setTargetHandle] = useState("");
  const [requestMessage, setRequestMessage] = useState("");
  const [groupName, setGroupName] = useState("");
  const [groupDescription, setGroupDescription] = useState("");
  const [personQuery, setPersonQuery] = useState("");
  const [people, setPeople] = useState<(CardSummary & { user_id: string })[]>([]);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const actionInFlight = useRef(false);
  // Keep the shared read cursor current while the legacy UI is still the
  // fallback. The v2 UI marks read explicitly on focus/visibility.
  const readSeq = useRef<Record<string, number>>({});
  const selectedConnection = connections.find((row) => row.id === connectionId);
  const selectedGroup = groups.find((row) => row.id === groupId);
  const connectionStatus = selectedConnection?.status;

  const incoming = useMemo(() => connections.filter((row) => row.status === "pending" && row.incoming), [connections]);

  async function loadConnections() {
    const result = await cardsNetworkRequest<{ connections: CardConnection[] }>("/connections", token);
    setConnections(result.connections);
  }

  async function loadGroups() {
    const [groupResult, inviteResult] = await Promise.all([
      cardsNetworkRequest<{ groups: CardGroup[] }>("/groups", token),
      cardsNetworkRequest<{ invitations: CardGroupInvitation[] }>("/group-invitations", token),
    ]);
    setGroups(groupResult.groups);
    setInvitations(inviteResult.invitations);
  }

  useEffect(() => {
    const controller = new AbortController();
    let loading = false;
    async function refresh() {
      if (loading || controller.signal.aborted) return;
      loading = true;
      try {
        const [connectionResult, groupResult, inviteResult] = await Promise.all([
          cardsNetworkRequest<{ connections: CardConnection[] }>("/connections", token, "GET", undefined, controller.signal),
          cardsNetworkRequest<{ groups: CardGroup[] }>("/groups", token, "GET", undefined, controller.signal),
          cardsNetworkRequest<{ invitations: CardGroupInvitation[] }>("/group-invitations", token, "GET", undefined, controller.signal),
        ]);
        if (!controller.signal.aborted) {
          setConnections(connectionResult.connections);
          setGroups(groupResult.groups);
          setInvitations(inviteResult.invitations);
        }
      } catch (error) {
        if (!controller.signal.aborted) setNotice(error instanceof Error ? error.message : "Could not load your network");
      } finally { loading = false; }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [token]);

  useEffect(() => {
    const controller = new AbortController();
    let loading = false;
    // Clear the previous conversation before fetching another one.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMessages([]);
    setDraft("");
    if (!connectionId || connectionStatus !== "accepted") return () => controller.abort();
    async function refresh() {
      if (loading || controller.signal.aborted) return;
      loading = true;
      try {
        const result = await cardsNetworkRequest<{ messages: CardMessage[] }>(`/connections/${connectionId}/messages`, token, "GET", undefined, controller.signal);
        if (!controller.signal.aborted) {
          setMessages(result.messages);
          const latest = result.messages[result.messages.length - 1];
          const key = `dm:${connectionId}`;
          if (latest?.seq && document.visibilityState === "visible" && latest.seq > (readSeq.current[key] ?? 0)) {
            readSeq.current[key] = latest.seq;
            void markNetworkRead(token, "dm", connectionId!, latest.seq).catch(() => { /* retried by the next poll */ });
          }
        }
      } catch (error) {
        if (!controller.signal.aborted) setNotice(error instanceof Error ? error.message : "Could not load messages");
      } finally { loading = false; }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [connectionId, connectionStatus, token]);

  useEffect(() => {
    const controller = new AbortController();
    let loading = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMembers([]);
    setGroupMessages([]);
    setGroupDraft("");
    setPeople([]);
    setPersonQuery("");
    if (!groupId) return () => controller.abort();
    async function refresh() {
      if (loading || controller.signal.aborted) return;
      loading = true;
      try {
        const [memberResult, messageResult] = await Promise.all([
          cardsNetworkRequest<{ members: CardGroupMember[] }>(`/groups/${groupId}/members`, token, "GET", undefined, controller.signal),
          cardsNetworkRequest<{ messages: CardMessage[] }>(`/groups/${groupId}/messages`, token, "GET", undefined, controller.signal),
        ]);
        if (!controller.signal.aborted) {
          setMembers(memberResult.members);
          setGroupMessages(messageResult.messages);
          const latest = messageResult.messages[messageResult.messages.length - 1];
          const key = `group:${groupId}`;
          if (latest?.seq && document.visibilityState === "visible" && latest.seq > (readSeq.current[key] ?? 0)) {
            readSeq.current[key] = latest.seq;
            void markNetworkRead(token, "group", groupId!, latest.seq).catch(() => { /* retried by the next poll */ });
          }
        }
      } catch (error) {
        if (!controller.signal.aborted) setNotice(error instanceof Error ? error.message : "Could not load the group");
      } finally { loading = false; }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [groupId, token]);

  async function run(action: () => Promise<void>) {
    if (actionInFlight.current) return;
    actionInFlight.current = true;
    setBusy(true);
    setNotice("");
    try { await action(); } catch (error) { setNotice(error instanceof Error ? error.message : "Something went wrong"); }
    finally { actionInFlight.current = false; setBusy(false); }
  }

  async function sendConnectionRequest() {
    await run(async () => {
      const result = await cardsNetworkRequest<{ connection: CardConnection; existing: boolean }>("/connections", token, "POST", { target_handle: targetHandle.trim(), message: requestMessage });
      setTargetHandle(""); setRequestMessage("");
      await loadConnections();
      setNotice(connectionRequestNotice(result));
    });
  }

  async function decideConnection(id: string, action: string) {
    await run(async () => { await cardsNetworkRequest(`/connections/${id}/respond`, token, "POST", { action }); await loadConnections(); });
  }

  async function sendMessage() {
    if (!selectedConnection || !draft.trim()) return;
    await run(async () => {
      await cardsNetworkRequest(`/connections/${selectedConnection.id}/messages`, token, "POST", { content: draft });
      setDraft("");
      const result = await cardsNetworkRequest<{ messages: CardMessage[] }>(`/connections/${selectedConnection.id}/messages`, token);
      setMessages(result.messages);
    });
  }

  async function createGroup() {
    if (!groupName.trim()) return;
    await run(async () => {
      await cardsNetworkRequest("/groups", token, "POST", { name: groupName, description: groupDescription, visibility: "private" });
      setGroupName(""); setGroupDescription(""); await loadGroups(); setNotice("Group created");
    });
  }

  async function searchPeople() {
    if (!selectedGroup) return;
    await run(async () => {
      const result = await cardsNetworkRequest<{ people: (CardSummary & { user_id: string })[] }>(`/groups/${selectedGroup.id}/people?query=${encodeURIComponent(personQuery)}`, token);
      setPeople(result.people);
    });
  }

  async function invite(handle: string) {
    if (!selectedGroup) return;
    await run(async () => { await cardsNetworkRequest(`/groups/${selectedGroup.id}/invitations`, token, "POST", { target_handle: handle }); setPeople([]); setPersonQuery(""); setNotice("Invitation sent"); });
  }

  async function decideInvite(id: string, decision: "accept" | "decline") {
    await run(async () => { await cardsNetworkRequest(`/group-invitations/${id}/respond`, token, "POST", { decision }); await loadGroups(); });
  }

  async function sendGroupMessage() {
    if (!selectedGroup || !groupDraft.trim()) return;
    await run(async () => {
      await cardsNetworkRequest(`/groups/${selectedGroup.id}/messages`, token, "POST", { content: groupDraft });
      setGroupDraft("");
      const result = await cardsNetworkRequest<{ messages: CardMessage[] }>(`/groups/${selectedGroup.id}/messages`, token);
      setGroupMessages(result.messages);
    });
  }

  return (
    <main style={{ minHeight: "calc(100vh - 80px)", color: "#f8fafc", padding: "56px 20px 100px" }}>
      <div style={{ maxWidth: 1180, margin: "0 auto" }}>
        <div style={{ marginBottom: 28 }}>
          <p style={{ color: "#818cf8", fontWeight: 800, letterSpacing: ".12em", fontSize: 12, textTransform: "uppercase" }}>Cards network</p>
          <h1 style={{ fontSize: "clamp(32px, 5vw, 56px)", margin: "8px 0", letterSpacing: "-.04em" }}>Your connections.</h1>
          <p style={{ color: "#a1a1aa", maxWidth: 650, lineHeight: 1.6 }}>Connect verified Cards, message accepted connections, and build small groups where every invitee chooses to join.</p>
        </div>
        {notice && <div role="status" style={{ ...panelStyle, marginBottom: 18, color: "#c7d2fe" }}>{notice}</div>}
        <div style={{ display: "flex", gap: 10, marginBottom: 18 }}>
          <button type="button" onClick={() => setTab("connections")} style={{ ...tabStyle, ...(tab === "connections" ? activeTab : {}) }}><MessageCircle size={16} /> Connections</button>
          <button type="button" onClick={() => setTab("groups")} style={{ ...tabStyle, ...(tab === "groups" ? activeTab : {}) }}><Users size={16} /> Groups</button>
        </div>

        {tab === "connections" ? (
          <div style={gridStyle}>
            <section style={panelStyle}>
              <h2 style={headingStyle}>Send a connection request</h2>
              <p style={mutedStyle}>Use the recipient&apos;s verified Card handle. They decide whether to accept.</p>
              <input aria-label="Card handle" value={targetHandle} onChange={(event) => setTargetHandle(event.target.value)} maxLength={128} placeholder="Card handle, e.g. alice" style={inputStyle} />
              <textarea aria-label="Connection note" value={requestMessage} onChange={(event) => setRequestMessage(event.target.value)} maxLength={2000} placeholder="Optional note" style={{ ...inputStyle, minHeight: 90, resize: "vertical" }} />
              <button type="button" disabled={busy || !targetHandle.trim()} onClick={() => void sendConnectionRequest()} style={primaryButton}><Send size={15} /> Send request</button>
              {incoming.length > 0 && <div style={{ marginTop: 28 }}>
                <h3 style={subheadingStyle}>Incoming requests</h3>
                {incoming.map((connection) => <div key={connection.id} style={rowStyle}>
                  <Avatar card={connection.partner} />
                  <div style={{ flex: 1, minWidth: 0 }}><strong>{connection.partner.name}</strong><div style={mutedStyle}>@{connection.partner.handle}</div>{connection.request_message && <p style={mutedStyle}>{connection.request_message}</p>}</div>
                  <button type="button" disabled={busy} aria-label={`Accept connection from ${connection.partner.name}`} onClick={() => void decideConnection(connection.id, "accept")} style={smallButton}><Check size={14} /> Accept</button>
                  <button type="button" disabled={busy} aria-label={`Decline connection from ${connection.partner.name}`} onClick={() => void decideConnection(connection.id, "decline")} style={smallDanger}><X size={14} /></button>
                </div>)}
              </div>}
            </section>
            <section style={panelStyle}>
              <h2 style={headingStyle}>Connections</h2>
              {connections.length === 0 ? <Empty>No connections yet. Send a request to a verified Card.</Empty> : connections.map((connection) => <button key={connection.id} type="button" disabled={busy} onClick={() => setConnectionId(connection.id)} style={{ ...connectionRow, ...(connectionId === connection.id ? selectedRow : {}) }}><Avatar card={connection.partner} /><span style={{ flex: 1, textAlign: "left" }}><strong>{connection.partner.name}</strong><small style={{ display: "block", color: "#a1a1aa" }}>@{connection.partner.handle}</small></span><Status status={connection.status} /></button>)}
            </section>
            <section style={{ ...panelStyle, gridColumn: "1 / -1" }}>
              <h2 style={headingStyle}>{selectedConnection ? `Conversation with ${selectedConnection.partner.name}` : "Direct messages"}</h2>
              {!selectedConnection || selectedConnection.status !== "accepted" ? <Empty>Select an accepted connection to message.</Empty> : <><div aria-label="Direct messages" style={chatBox}>{messages.map((message) => <div key={message.id} style={{ ...bubble, alignSelf: message.sender_user_id === userId ? "flex-end" : "flex-start", background: message.sender_user_id === userId ? "#3730a3" : "#1f2937" }}>{message.content}</div>)}</div><div style={{ display: "flex", gap: 10 }}><input aria-label="Direct message" maxLength={4000} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void sendMessage(); } }} placeholder="Write a message" style={{ ...inputStyle, margin: 0 }} /><button type="button" aria-label="Send direct message" disabled={busy || !draft.trim()} onClick={() => void sendMessage()} style={primaryButton}><Send size={15} /></button></div></>}
            </section>
          </div>
        ) : (
          <div style={gridStyle}>
            <section style={panelStyle}>
              <h2 style={headingStyle}>Create a group</h2>
              <input aria-label="Group name" maxLength={80} value={groupName} onChange={(event) => setGroupName(event.target.value)} placeholder="Group name" style={inputStyle} />
              <textarea aria-label="Group description" maxLength={500} value={groupDescription} onChange={(event) => setGroupDescription(event.target.value)} placeholder="What is this group for?" style={{ ...inputStyle, minHeight: 80, resize: "vertical" }} />
              <button type="button" disabled={busy || !groupName.trim()} onClick={() => void createGroup()} style={primaryButton}><Plus size={15} /> Create group</button>
              {invitations.length > 0 && <div style={{ marginTop: 26 }}><h3 style={subheadingStyle}>Group invitations</h3>{invitations.map((invitation) => <div key={invitation.id} style={rowStyle}><span style={{ flex: 1 }}>Invitation to {invitation.group?.name || "a group"}{invitation.message && <small style={{ display: "block" }}>{invitation.message}</small>}</span><button type="button" disabled={busy} aria-label={`Accept invitation to ${invitation.group?.name || "group"}`} onClick={() => void decideInvite(invitation.id, "accept")} style={smallButton}>Accept</button><button type="button" disabled={busy} aria-label={`Decline invitation to ${invitation.group?.name || "group"}`} onClick={() => void decideInvite(invitation.id, "decline")} style={smallDanger}><X size={14} /></button></div>)}</div>}
            </section>
            <section style={panelStyle}>
              <h2 style={headingStyle}>Your groups</h2>
              {groups.length === 0 ? <Empty>Create a group to start a shared conversation.</Empty> : groups.map((group) => <button key={group.id} type="button" disabled={busy} onClick={() => setGroupId(group.id)} style={{ ...connectionRow, ...(groupId === group.id ? selectedRow : {}) }}><Users size={20} color="#818cf8" /><span style={{ flex: 1, textAlign: "left" }}><strong>{group.name}</strong><small style={{ display: "block", color: "#a1a1aa" }}>{group.my_role}</small></span></button>)}
            </section>
            <section style={{ ...panelStyle, gridColumn: "1 / -1" }}>
              <h2 style={headingStyle}>{selectedGroup ? selectedGroup.name : "Group workspace"}</h2>
              {!selectedGroup ? <Empty>Select a group to see its members and messages.</Empty> : <>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 18 }}>{members.map((member) => <span key={member.id} style={memberPill}>{member.card?.name || member.user_id}</span>)}</div>
                {selectedGroup.my_role === "owner" && <>
                  <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
                    <input aria-label="Search connected Cards" maxLength={120} value={personQuery} onChange={(event) => setPersonQuery(event.target.value)} placeholder="Search connected Cards to invite" style={{ ...inputStyle, margin: 0 }} />
                    <button type="button" disabled={busy} aria-label="Search people to invite" onClick={() => void searchPeople()} style={secondaryButton}><Search size={15} /></button>
                  </div>
                  {people.length > 0 && <div style={{ marginBottom: 18 }}>{people.map((person) => <div key={person.user_id} style={rowStyle}><Avatar card={person} /><span style={{ flex: 1 }}>{person.name} <small style={{ color: "#a1a1aa" }}>@{person.handle}</small></span><button type="button" disabled={busy} onClick={() => void invite(person.handle || "")} style={smallButton}>Invite</button></div>)}</div>}
                </>}
                <div aria-label="Group messages" style={chatBox}>{groupMessages.map((message) => <div key={message.id} style={{ ...bubble, alignSelf: message.sender_user_id === userId ? "flex-end" : "flex-start", background: message.sender_user_id === userId ? "#3730a3" : "#1f2937" }}>{message.content}</div>)}</div>
                <div style={{ display: "flex", gap: 10 }}>
                  <input aria-label="Group message" maxLength={4000} value={groupDraft} onChange={(event) => setGroupDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void sendGroupMessage(); } }} placeholder="Message the group" style={{ ...inputStyle, margin: 0 }} />
                  <button type="button" aria-label="Send group message" disabled={busy || !groupDraft.trim()} onClick={() => void sendGroupMessage()} style={primaryButton}><Send size={15} /></button>
                </div>
              </>}
            </section>
          </div>
        )}
      </div>
    </main>
  );
}

function Status({ status }: { status: CardConnection["status"] }) {
  return <span style={{ color: status === "accepted" ? "#86efac" : "#fcd34d", fontSize: 12, textTransform: "capitalize" }}>{status}</span>;
}

const tabStyle: React.CSSProperties = { display: "inline-flex", alignItems: "center", gap: 8, borderWidth: 1, borderStyle: "solid", borderColor: "rgba(255,255,255,.12)", background: "transparent", color: "#cbd5e1", borderRadius: 999, padding: "10px 16px", cursor: "pointer" };
const activeTab: React.CSSProperties = { background: "#312e81", color: "white", borderColor: "#6366f1" };
const gridStyle: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(min(100%,300px),1fr))", gap: 18 };
const headingStyle: React.CSSProperties = { fontSize: 20, margin: "0 0 8px" };
const subheadingStyle: React.CSSProperties = { fontSize: 14, margin: "0 0 10px", color: "#c7d2fe" };
const mutedStyle: React.CSSProperties = { color: "#9ca3af", fontSize: 13, lineHeight: 1.5, margin: "0 0 12px" };
const inputStyle: React.CSSProperties = { width: "100%", boxSizing: "border-box", margin: "0 0 10px", border: "1px solid rgba(255,255,255,.14)", background: "rgba(0,0,0,.22)", color: "white", borderRadius: 10, padding: "12px 13px", font: "inherit" };
const primaryButton: React.CSSProperties = { display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 7, border: 0, borderRadius: 10, padding: "11px 15px", background: "#4f46e5", color: "white", fontWeight: 700, cursor: "pointer" };
const secondaryButton: React.CSSProperties = { ...primaryButton, background: "#1f2937" };
const smallButton: React.CSSProperties = { ...primaryButton, padding: "7px 10px", fontSize: 12 };
const smallDanger: React.CSSProperties = { ...smallButton, background: "#4c1d1d" };
const rowStyle: React.CSSProperties = { display: "flex", alignItems: "center", gap: 10, padding: "10px 0", borderBottom: "1px solid rgba(255,255,255,.07)" };
const connectionRow: React.CSSProperties = { width: "100%", display: "flex", alignItems: "center", gap: 12, padding: "12px 0", border: 0, borderBottom: "1px solid rgba(255,255,255,.07)", background: "transparent", color: "white", cursor: "pointer" };
const selectedRow: React.CSSProperties = { background: "rgba(79,70,229,.15)", borderRadius: 10, paddingLeft: 10, paddingRight: 10 };
const memberPill: React.CSSProperties = { borderRadius: 999, padding: "6px 10px", background: "rgba(99,102,241,.18)", color: "#c7d2fe", fontSize: 12 };
const chatBox: React.CSSProperties = { minHeight: 150, maxHeight: 360, overflowY: "auto", display: "flex", flexDirection: "column", gap: 8, padding: 12, marginBottom: 12, background: "rgba(0,0,0,.18)", borderRadius: 12 };
const bubble: React.CSSProperties = { maxWidth: "75%", padding: "9px 12px", borderRadius: 12, lineHeight: 1.45, whiteSpace: "pre-wrap", overflowWrap: "anywhere" };
