"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, MessageCircle, Plus, Search, Send, Users, X } from "lucide-react";
import {
  cardsNetworkRequest,
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
  const [selectedConnection, setSelectedConnection] = useState<CardConnection | null>(null);
  const [selectedGroup, setSelectedGroup] = useState<CardGroup | null>(null);
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
    // These loaders intentionally update the view from authenticated network data.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void Promise.all([loadConnections(), loadGroups()]).catch((error: unknown) => setNotice(error instanceof Error ? error.message : "Could not load your network"));
    // The access token is stable for this page session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    if (!selectedConnection || selectedConnection.status !== "accepted") {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMessages([]);
      return;
    }
    void cardsNetworkRequest<{ messages: CardMessage[] }>(`/connections/${selectedConnection.id}/messages`, token)
      .then((result) => setMessages(result.messages))
      .catch((error: unknown) => setNotice(error instanceof Error ? error.message : "Could not load messages"));
  }, [selectedConnection, token]);

  useEffect(() => {
    if (!selectedGroup) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMembers([]);
      setGroupMessages([]);
      return;
    }
    void Promise.all([
      cardsNetworkRequest<{ members: CardGroupMember[] }>(`/groups/${selectedGroup.id}/members`, token),
      cardsNetworkRequest<{ messages: CardMessage[] }>(`/groups/${selectedGroup.id}/messages`, token),
    ]).then(([memberResult, messageResult]) => {
      setMembers(memberResult.members);
      setGroupMessages(messageResult.messages);
    }).catch((error: unknown) => setNotice(error instanceof Error ? error.message : "Could not load the group"));
  }, [selectedGroup, token]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setNotice("");
    try { await action(); } catch (error) { setNotice(error instanceof Error ? error.message : "Something went wrong"); }
    finally { setBusy(false); }
  }

  async function sendConnectionRequest() {
    await run(async () => {
      await cardsNetworkRequest("/connections", token, "POST", { target_handle: targetHandle, message: requestMessage });
      setTargetHandle(""); setRequestMessage("");
      await loadConnections();
      setNotice("Connection request sent");
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
              <input value={targetHandle} onChange={(event) => setTargetHandle(event.target.value)} placeholder="Card handle, e.g. alice" style={inputStyle} />
              <textarea value={requestMessage} onChange={(event) => setRequestMessage(event.target.value)} placeholder="Optional note" style={{ ...inputStyle, minHeight: 90, resize: "vertical" }} />
              <button type="button" disabled={busy || !targetHandle.trim()} onClick={() => void sendConnectionRequest()} style={primaryButton}><Send size={15} /> Send request</button>
              {incoming.length > 0 && <div style={{ marginTop: 28 }}><h3 style={subheadingStyle}>Incoming requests</h3>{incoming.map((connection) => <div key={connection.id} style={rowStyle}><Avatar card={connection.partner} /><div style={{ flex: 1 }}><strong>{connection.partner.name}</strong><div style={mutedStyle}>@{connection.partner.handle}</div></div><button type="button" onClick={() => void decideConnection(connection.id, "accept")} style={smallButton}><Check size={14} /> Accept</button><button type="button" onClick={() => void decideConnection(connection.id, "decline")} style={smallDanger}><X size={14} /></button></div>)}</div>}
            </section>
            <section style={panelStyle}>
              <h2 style={headingStyle}>Connections</h2>
              {connections.length === 0 ? <Empty>No connections yet. Send a request to a verified Card.</Empty> : connections.map((connection) => <button key={connection.id} type="button" onClick={() => setSelectedConnection(connection)} style={{ ...connectionRow, ...(selectedConnection?.id === connection.id ? selectedRow : {}) }}><Avatar card={connection.partner} /><span style={{ flex: 1, textAlign: "left" }}><strong>{connection.partner.name}</strong><small style={{ display: "block", color: "#a1a1aa" }}>@{connection.partner.handle}</small></span><Status status={connection.status} /></button>)}
            </section>
            <section style={{ ...panelStyle, gridColumn: "1 / -1" }}>
              <h2 style={headingStyle}>{selectedConnection ? `Conversation with ${selectedConnection.partner.name}` : "Direct messages"}</h2>
              {!selectedConnection || selectedConnection.status !== "accepted" ? <Empty>Select an accepted connection to message.</Empty> : <><div style={chatBox}>{messages.map((message) => <div key={message.id} style={{ ...bubble, alignSelf: message.sender_user_id === userId ? "flex-end" : "flex-start", background: message.sender_user_id === userId ? "#3730a3" : "#1f2937" }}>{message.content}</div>)}</div><div style={{ display: "flex", gap: 10 }}><input value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void sendMessage(); } }} placeholder="Write a message" style={{ ...inputStyle, margin: 0 }} /><button type="button" disabled={busy || !draft.trim()} onClick={() => void sendMessage()} style={primaryButton}><Send size={15} /></button></div></>}
            </section>
          </div>
        ) : (
          <div style={gridStyle}>
            <section style={panelStyle}>
              <h2 style={headingStyle}>Create a group</h2>
              <input value={groupName} onChange={(event) => setGroupName(event.target.value)} placeholder="Group name" style={inputStyle} />
              <textarea value={groupDescription} onChange={(event) => setGroupDescription(event.target.value)} placeholder="What is this group for?" style={{ ...inputStyle, minHeight: 80, resize: "vertical" }} />
              <button type="button" disabled={busy || !groupName.trim()} onClick={() => void createGroup()} style={primaryButton}><Plus size={15} /> Create group</button>
              {invitations.length > 0 && <div style={{ marginTop: 26 }}><h3 style={subheadingStyle}>Group invitations</h3>{invitations.map((invitation) => <div key={invitation.id} style={rowStyle}><span style={{ flex: 1 }}>Invitation to join a group</span><button type="button" onClick={() => void decideInvite(invitation.id, "accept")} style={smallButton}>Accept</button><button type="button" onClick={() => void decideInvite(invitation.id, "decline")} style={smallDanger}><X size={14} /></button></div>)}</div>}
            </section>
            <section style={panelStyle}>
              <h2 style={headingStyle}>Your groups</h2>
              {groups.length === 0 ? <Empty>Create a group to start a shared conversation.</Empty> : groups.map((group) => <button key={group.id} type="button" onClick={() => setSelectedGroup(group)} style={{ ...connectionRow, ...(selectedGroup?.id === group.id ? selectedRow : {}) }}><Users size={20} color="#818cf8" /><span style={{ flex: 1, textAlign: "left" }}><strong>{group.name}</strong><small style={{ display: "block", color: "#a1a1aa" }}>{group.my_role}</small></span></button>)}
            </section>
            <section style={{ ...panelStyle, gridColumn: "1 / -1" }}>
              <h2 style={headingStyle}>{selectedGroup ? selectedGroup.name : "Group workspace"}</h2>
              {!selectedGroup ? <Empty>Select a group to see its members and messages.</Empty> : <><div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 18 }}>{members.map((member) => <span key={member.id} style={memberPill}>{member.card?.name || member.user_id}</span>)}</div><div style={{ display: "flex", gap: 8, marginBottom: 18 }}><input value={personQuery} onChange={(event) => setPersonQuery(event.target.value)} placeholder="Search connected Cards to invite" style={{ ...inputStyle, margin: 0 }} /><button type="button" onClick={() => void searchPeople()} style={secondaryButton}><Search size={15} /></button></div>{people.length > 0 && <div style={{ marginBottom: 18 }}>{people.map((person) => <div key={person.user_id} style={rowStyle}><Avatar card={person} /><span style={{ flex: 1 }}>{person.name} <small style={{ color: "#a1a1aa" }}>@{person.handle}</small></span><button type="button" onClick={() => void invite(person.handle || "")} style={smallButton}>Invite</button></div>)}</div>}<div style={chatBox}>{groupMessages.map((message) => <div key={message.id} style={{ ...bubble, alignSelf: message.sender_user_id === userId ? "flex-end" : "flex-start", background: message.sender_user_id === userId ? "#3730a3" : "#1f2937" }}>{message.content}</div>)}</div><div style={{ display: "flex", gap: 10 }}><input value={groupDraft} onChange={(event) => setGroupDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void sendGroupMessage(); } }} placeholder="Message the group" style={{ ...inputStyle, margin: 0 }} /><button type="button" disabled={busy || !groupDraft.trim()} onClick={() => void sendGroupMessage()} style={primaryButton}><Send size={15} /></button></div></>}
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

const tabStyle: React.CSSProperties = { display: "inline-flex", alignItems: "center", gap: 8, border: "1px solid rgba(255,255,255,.12)", background: "transparent", color: "#cbd5e1", borderRadius: 999, padding: "10px 16px", cursor: "pointer" };
const activeTab: React.CSSProperties = { background: "#312e81", color: "white", borderColor: "#6366f1" };
const gridStyle: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(300px,1fr))", gap: 18 };
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
const bubble: React.CSSProperties = { maxWidth: "75%", padding: "9px 12px", borderRadius: 12, lineHeight: 1.45, whiteSpace: "pre-wrap" };
