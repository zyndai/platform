"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Bookmark,
  BookmarkCheck,
  Bot,
  Brain,
  Check,
  Clock3,
  Inbox,
  Loader2,
  MessageCircle,
  Plus,
  Search,
  Send,
  Sparkles,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import {
  cardsNetworkRequest,
  connectionRequestNotice,
  fetchAgentPreference,
  fetchDmMessages,
  fetchGroupMemory,
  fetchGroupMessages,
  fetchInbox,
  markNetworkRead,
  rememberGroupMessage,
  searchGroupMemory,
  sendDm,
  sendGroupMessage,
  setAgentPreference as saveAgentPreference,
  type CardAgentPreference,
  type CardConnection,
  type CardGroup,
  type CardGroupInvitation,
  type CardGroupMember,
  type CardGroupMemory,
  type CardGroupMemoryList,
  type CardInbox,
  type CardMessage,
  type CardSummary,
  type NetworkConversation,
} from "@/lib/cards-network";
import {
  cacheInbox,
  cacheMembers,
  cacheThreadMessage,
  cacheThreadPage,
  cacheThreadPeerRead,
  getCachedInbox,
  getCachedMembers,
  getCachedThread,
  hydrateNetworkCache,
  markCachedMessageRemembered,
  mergeMessages,
  removeCachedMessage,
  threadKey,
  useNetworkCache,
  type NetworkThreadKind,
} from "@/lib/network-cache";
import {
  useNetworkRealtime,
  type NetworkRealtimeEvent,
} from "@/lib/use-network-realtime";
import "./network-v2.css";

type Tab = "all" | "dms" | "groups" | "requests";
type InboxItem = { kind: "dm"; connection: CardConnection } | { kind: "group"; group: CardGroup };
type InboxUpdater = CardInbox | null | ((current: CardInbox | null) => CardInbox | null);

function newClientId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `10000000-1000-4000-8000-${String(Date.now()).padStart(12, "0").slice(-12)}`;
}

function dayKey(iso: string): string {
  const date = new Date(iso);
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

function dayLabel(iso: string): string {
  const date = new Date(iso);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (dayKey(iso) === dayKey(today.toISOString())) return "Today";
  if (dayKey(iso) === dayKey(yesterday.toISOString())) return "Yesterday";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: date.getFullYear() === today.getFullYear() ? undefined : "numeric" });
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function relativeTime(iso?: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return "now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  if (seconds < 604800) return `${Math.floor(seconds / 86400)}d`;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function previewText(text?: string | null): string {
  return (text || "").replace(/\s+/g, " ").trim().slice(0, 140);
}

function renderMessageContent(content: string) {
  return content.split(/(@[A-Za-z0-9_.-]{1,64})/g).map((part, index) => (
    part.startsWith("@")
      ? <span className="nv2-mention" key={`${part}-${index}`}>{part}</span>
      : <span key={`text-${index}`}>{part}</span>
  ));
}

function isAgentMessage(message: CardMessage): boolean {
  return message.sender_kind === "agent";
}

function activeMention(value: string, caret: number): { start: number; query: string } | null {
  const before = value.slice(0, caret);
  const match = before.match(/(?:^|\s)@([A-Za-z0-9_.-]*)$/);
  if (!match) return null;
  return { start: before.lastIndexOf("@"), query: match[1] };
}

function activityAt(item: InboxItem): string {
  if (item.kind === "dm") {
    return item.connection.last_message_at || item.connection.updated_at || item.connection.created_at;
  }
  return item.group.last_message_at || item.group.updated_at || item.group.created_at;
}

function Avatar({
  card,
  name,
  size = 42,
  group = false,
  small = false,
}: {
  card?: CardSummary | null;
  name?: string;
  size?: number;
  group?: boolean;
  small?: boolean;
}) {
  const label = (card?.name || name || "?").slice(0, 1).toUpperCase();
  return (
    <span
      className={`nv2-avatar${group ? " is-group" : ""}${small ? " is-small" : ""}`}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.38) }}
      aria-hidden="true"
    >
      {card?.avatar_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={card.avatar_url} alt="" />
      ) : label}
    </span>
  );
}

function asMessage(value: unknown): CardMessage | null {
  if (!value || typeof value !== "object") return null;
  const message = value as Partial<CardMessage>;
  if (typeof message.id !== "string" || typeof message.content !== "string" || typeof message.sender_user_id !== "string") {
    return null;
  }
  return {
    ...message,
    created_at: typeof message.created_at === "string" ? message.created_at : new Date().toISOString(),
    seq: message.seq == null ? undefined : Number(message.seq),
  } as CardMessage;
}

export function NetworkV2({
  token,
  userId,
  groupMemoryEnabled = false,
  groupAgentRepliesEnabled = false,
}: {
  token: string;
  userId: string;
  groupMemoryEnabled?: boolean;
  groupAgentRepliesEnabled?: boolean;
}) {
  const cachedInbox = getCachedInbox();
  const cache = useNetworkCache();
  const [inbox, setInboxState] = useState<CardInbox | null>(cachedInbox);
  const [loading, setLoading] = useState(!cachedInbox);
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const [tab, setTab] = useState<Tab>("all");
  const [search, setSearch] = useState("");
  const [selectedKind, setSelectedKind] = useState<"dm" | "group" | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [composer, setComposer] = useState<"connection" | "group" | null>(null);
  const [busy, setBusy] = useState(false);
  const [membersByGroup, setMembersByGroup] = useState<Record<string, CardGroupMember[]>>({});
  const memberRequests = useRef(new Set<string>());
  const loadedMembers = useRef(new Set<string>());
  const refreshTimer = useRef<number | null>(null);
  const prefetching = useRef(new Set<string>());
  const prefetchedInitial = useRef(false);
  const inboxRef = useRef<CardInbox | null>(cachedInbox);

  const setInbox = useCallback((updater: InboxUpdater) => {
    const current = inboxRef.current;
    const next = typeof updater === "function" ? updater(current) : updater;
    inboxRef.current = next;
    setInboxState(next);
    if (next) cacheInbox(next);
  }, []);

  const loadInbox = useCallback(async (signal?: AbortSignal) => {
    try {
      const data = await fetchInbox(token, signal);
      setInbox(data);
      setLoadError("");
    } catch (error) {
      if (!signal?.aborted) setLoadError(error instanceof Error ? error.message : "Could not load your network");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [setInbox, token]);

  useEffect(() => {
    inboxRef.current = inbox;
  }, [inbox]);

  useEffect(() => {
    if (!inbox && cache.inbox) {
      // IndexedDB hydration can finish after the first render.
      inboxRef.current = cache.inbox;
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setInboxState(cache.inbox);
      setLoading(false);
    }
  }, [cache.inbox, inbox]);

  useEffect(() => {
    const controller = new AbortController();
    // Wait for the persisted cache so the first paint can use it, then refresh
    // from the server in the background.
    void hydrateNetworkCache(userId).finally(() => {
      if (!controller.signal.aborted) void loadInbox(controller.signal);
    });
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void loadInbox();
    }, 30_000);
    const onVisible = () => {
      if (document.visibilityState === "visible") void loadInbox();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    return () => {
      controller.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
  }, [loadInbox, userId]);

  const scheduleInboxRefresh = useCallback(() => {
    if (refreshTimer.current) window.clearTimeout(refreshTimer.current);
    refreshTimer.current = window.setTimeout(() => void loadInbox(), 250);
  }, [loadInbox]);

  const onUserRealtime = useCallback((event: NetworkRealtimeEvent) => {
    if (event.event === "member" && typeof event.payload.group_id === "string") {
      const groupId = event.payload.group_id;
      loadedMembers.current.delete(groupId);
      setMembersByGroup((current) => {
        if (!(groupId in current)) return current;
        const next = { ...current };
        delete next[groupId];
        return next;
      });
    }
    scheduleInboxRefresh();
  }, [scheduleInboxRefresh]);

  useNetworkRealtime({
    token,
    topic: `cards:user:${userId}`,
    events: ["inbox", "connection", "invitation", "member"],
    onEvent: onUserRealtime,
    onReconnect: () => void loadInbox(),
  });

  const unread = useMemo(() => {
    const dm = (inbox?.connections ?? []).reduce(
      (total, connection) => total + (connection.status === "accepted" ? connection.unread_count ?? 0 : 0),
      0,
    );
    const groups = (inbox?.groups ?? []).reduce((total, group) => total + (group.unread_count ?? 0), 0);
    return dm + groups;
  }, [inbox]);

  useEffect(() => {
    document.title = unread > 0 ? `(${unread}) Messages · Zynd Cards` : "Messages · Zynd Cards";
  }, [unread]);

  const selected = useMemo<NetworkConversation | null>(() => {
    if (!inbox || !selectedKind || !selectedId) return null;
    if (selectedKind === "dm") {
      const connection = inbox.connections.find((row) => row.id === selectedId);
      return connection && connection.status === "accepted"
        ? { kind: "dm", id: connection.id, connection }
        : null;
    }
    const group = inbox.groups.find((row) => row.id === selectedId);
    return group ? { kind: "group", id: group.id, group } : null;
  }, [inbox, selectedId, selectedKind]);

  const loadMembers = useCallback(async (groupId: string) => {
    if (memberRequests.current.has(groupId) || loadedMembers.current.has(groupId)) return;
    const cached = getCachedMembers(groupId);
    if (cached) {
      loadedMembers.current.add(groupId);
      setMembersByGroup((current) => ({ ...current, [groupId]: cached }));
      return;
    }
    memberRequests.current.add(groupId);
    try {
      const result = await cardsNetworkRequest<{ members: CardGroupMember[] }>(`/groups/${groupId}/members`, token);
      loadedMembers.current.add(groupId);
      cacheMembers(groupId, result.members);
      setMembersByGroup((current) => ({ ...current, [groupId]: result.members }));
    } catch {
      // Member metadata is non-fatal; the conversation still works.
    } finally {
      memberRequests.current.delete(groupId);
    }
  }, [token]);

  const prefetchConversation = useCallback(async (kind: NetworkThreadKind, id: string) => {
    const key = threadKey(kind, id);
    if (prefetching.current.has(key)) return;
    const cached = getCachedThread(kind, id);
    if (cached && Date.now() - cached.updatedAt < 15_000) return;
    prefetching.current.add(key);
    try {
      const page = kind === "dm"
        ? await fetchDmMessages(token, id, { limit: 40, afterSeq: cached?.latestSeq || undefined })
        : await fetchGroupMessages(token, id, { limit: 40, afterSeq: cached?.latestSeq || undefined });
      cacheThreadPage(kind, id, page, cached?.latestSeq ? "newer" : "initial");
    } catch {
      // Prefetch is best effort; opening the conversation will retry.
    } finally {
      prefetching.current.delete(key);
    }
  }, [token]);

  function selectConversation(kind: "dm" | "group", id: string) {
    setSelectedKind(kind);
    setSelectedId(id);
    setMobileOpen(true);
    if (kind === "group") void loadMembers(id);
  }

  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setNotice("");
    try {
      await action();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  async function decideConnection(id: string, action: "accept" | "decline") {
    await run(async () => {
      await cardsNetworkRequest(`/connections/${id}/respond`, token, "POST", { action });
      await loadInbox();
      if (action === "accept") selectConversation("dm", id);
      setNotice(action === "accept" ? "Connection accepted" : "Connection declined");
    });
  }

  async function decideInvitation(invitation: CardGroupInvitation, decision: "accept" | "decline") {
    await run(async () => {
      await cardsNetworkRequest(`/group-invitations/${invitation.id}/respond`, token, "POST", { decision });
      await loadInbox();
      if (decision === "accept") selectConversation("group", invitation.group_id);
      setNotice(decision === "accept" ? "Group joined" : "Invitation declined");
    });
  }

  const onInboxActivity = useCallback((kind: "dm" | "group", id: string, message: CardMessage, unreadDelta: number) => {
    setInbox((current) => {
      if (!current) return current;
      const preview = message.sender_kind === "agent"
        ? `AI: ${previewText(message.content)}`
        : previewText(message.content);
      if (kind === "dm") {
        return {
          ...current,
          connections: current.connections.map((connection) => connection.id === id
            ? {
                ...connection,
                last_message_at: message.created_at,
                last_message_preview: preview,
                last_message_sender_user_id: message.sender_user_id,
                unread_count: message.sender_user_id === userId
                  ? 0
                  : Math.max(0, (connection.unread_count ?? 0) + unreadDelta),
              }
            : connection),
        };
      }
      return {
        ...current,
        groups: current.groups.map((group) => group.id === id
          ? {
              ...group,
              last_message_at: message.created_at,
              last_message_preview: preview,
              last_message_sender_user_id: message.sender_user_id,
              unread_count: message.sender_user_id === userId
                ? 0
                : Math.max(0, (group.unread_count ?? 0) + unreadDelta),
            }
          : group),
      };
    });
  }, [setInbox, userId]);

  const onConversationRead = useCallback((kind: "dm" | "group", id: string) => {
    setInbox((current) => {
      if (!current) return current;
      if (kind === "dm") {
        return { ...current, connections: current.connections.map((row) => row.id === id ? { ...row, unread_count: 0 } : row) };
      }
      return { ...current, groups: current.groups.map((row) => row.id === id ? { ...row, unread_count: 0 } : row) };
    });
  }, [setInbox]);

  const acceptedDms = useMemo(
    () => (inbox?.connections ?? []).filter((connection) => connection.status === "accepted"),
    [inbox],
  );
  const pendingConnections = useMemo(
    () => (inbox?.connections ?? []).filter((connection) => connection.status === "pending"),
    [inbox],
  );
  const invitations = useMemo(() => inbox?.invitations ?? [], [inbox]);
  const groups = useMemo(() => inbox?.groups ?? [], [inbox]);
  const requestsCount = pendingConnections.length + invitations.length;

  const query = search.trim().toLowerCase();
  const matches = useCallback((...values: (string | null | undefined)[]) =>
    !query || values.some((value) => (value || "").toLowerCase().includes(query)), [query]);

  const dmItems: InboxItem[] = useMemo(() => acceptedDms
    .filter((connection) => matches(connection.partner.name, connection.partner.handle, connection.last_message_preview))
    .map((connection) => ({ kind: "dm" as const, connection })), [acceptedDms, matches]);

  const groupItems: InboxItem[] = useMemo(() => groups
    .filter((group) => matches(group.name, group.description, group.last_message_preview))
    .map((group) => ({ kind: "group" as const, group })), [groups, matches]);

  const conversationItems = useMemo(() => {
    const items = tab === "groups" ? groupItems : tab === "dms" ? dmItems : [...dmItems, ...groupItems];
    return [...items].sort((a, b) => activityAt(b).localeCompare(activityAt(a)));
  }, [dmItems, groupItems, tab]);

  useEffect(() => {
    if (!inbox || prefetchedInitial.current) return;
    prefetchedInitial.current = true;
    const recent = [
      ...acceptedDms.map((connection) => ({ kind: "dm" as const, id: connection.id, at: activityAt({ kind: "dm", connection }) })),
      ...groups.map((group) => ({ kind: "group" as const, id: group.id, at: activityAt({ kind: "group", group }) })),
    ].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 3);
    const timer = window.setTimeout(() => {
      for (const item of recent) void prefetchConversation(item.kind, item.id);
    }, 500);
    return () => window.clearTimeout(timer);
  }, [acceptedDms, groups, inbox, prefetchConversation]);

  const selectedGroupMembers = selected?.kind === "group" ? membersByGroup[selected.group.id] : undefined;
  const showMobileMain = Boolean(mobileOpen && selected);

  return (
    <main className="nv2-page">
      {notice && <div className="nv2-notice" role="status">{notice}</div>}
      {loadError && <div className="nv2-notice" role="alert">{loadError}</div>}
      <div className={`nv2-shell${showMobileMain ? " is-open" : ""}`}>
        <aside className="nv2-sidebar">
          <div className="nv2-sidebar-head">
            <div>
              <span className="nv2-eyebrow">Cards network</span>
              <h1 className="nv2-title">Messages</h1>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button type="button" className="nv2-icon-button" aria-label="Start a connection" onClick={() => setComposer("connection")}>
                <UserPlus size={17} />
              </button>
              <button type="button" className="nv2-icon-button" aria-label="Create a group" onClick={() => setComposer("group")}>
                <Plus size={18} />
              </button>
            </div>
          </div>

          <div className="nv2-tabs" role="tablist" aria-label="Network filters">
            <button type="button" role="tab" aria-selected={tab === "all"} className={`nv2-tab${tab === "all" ? " is-active" : ""}`} onClick={() => setTab("all")}>
              <Inbox size={13} /> All
            </button>
            <button type="button" role="tab" aria-selected={tab === "dms"} className={`nv2-tab${tab === "dms" ? " is-active" : ""}`} onClick={() => setTab("dms")}>
              <MessageCircle size={13} /> DMs
            </button>
            <button type="button" role="tab" aria-selected={tab === "groups"} className={`nv2-tab${tab === "groups" ? " is-active" : ""}`} onClick={() => setTab("groups")}>
              <Users size={13} /> Groups
            </button>
            <button type="button" role="tab" aria-selected={tab === "requests"} className={`nv2-tab${tab === "requests" ? " is-active" : ""}`} onClick={() => setTab("requests")}>
              <Clock3 size={13} /> Requests {requestsCount > 0 && <span className="nv2-tab-count">{requestsCount}</span>}
            </button>
          </div>

          <div className="nv2-search-wrap">
            <Search size={15} className="nv2-search-icon" />
            <input
              className="nv2-search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search people, groups, messages"
              aria-label="Search your network"
              maxLength={120}
            />
          </div>

          <div className="nv2-list">
            {loading && !inbox ? (
              <>
                <div className="nv2-skeleton" />
                <div className="nv2-skeleton" />
                <div className="nv2-skeleton" />
              </>
            ) : (
              <>
                {(tab === "all" || tab === "requests") && requestsCount > 0 && (
                  <>
                    <div className="nv2-section-label"><span>Requests</span><span>{requestsCount}</span></div>
                    {pendingConnections.map((connection) => (
                      <div className="nv2-item" key={connection.id}>
                        <Avatar card={connection.partner} />
                        <div className="nv2-item-main">
                          <div className="nv2-item-top">
                            <span className="nv2-item-name">{connection.partner.name}</span>
                            <span className="nv2-item-time">{relativeTime(connection.created_at)}</span>
                          </div>
                          <div className="nv2-item-preview">
                            <span>{connection.incoming ? connection.request_message || "Wants to connect" : "Request pending"}</span>
                          </div>
                        </div>
                        {connection.incoming && (
                          <div className="nv2-request-actions">
                            <button
                              type="button"
                              className="nv2-small-button"
                              aria-label={`Accept connection from ${connection.partner.name}`}
                              disabled={busy}
                              onClick={() => void decideConnection(connection.id, "accept")}
                            >
                              <Check size={13} />
                            </button>
                            <button
                              type="button"
                              className="nv2-small-button is-danger"
                              aria-label={`Decline connection from ${connection.partner.name}`}
                              disabled={busy}
                              onClick={() => void decideConnection(connection.id, "decline")}
                            >
                              <X size={13} />
                            </button>
                          </div>
                        )}
                      </div>
                    ))}
                    {invitations.map((invitation) => {
                      const name = invitation.group?.name || "a group";
                      return (
                        <div className="nv2-item" key={invitation.id}>
                          <Avatar name={name} group size={42} />
                          <div className="nv2-item-main">
                            <div className="nv2-item-top">
                              <span className="nv2-item-name">{name}</span>
                              <span className="nv2-item-time">{relativeTime(invitation.created_at)}</span>
                            </div>
                            <div className="nv2-item-preview"><span>{invitation.message || "Invited you to join"}</span></div>
                          </div>
                          <div className="nv2-request-actions">
                            <button
                              type="button"
                              className="nv2-small-button"
                              aria-label={`Accept invitation to ${name}`}
                              disabled={busy}
                              onClick={() => void decideInvitation(invitation, "accept")}
                            >
                              Accept
                            </button>
                            <button
                              type="button"
                              className="nv2-small-button is-danger"
                              aria-label={`Decline invitation to ${name}`}
                              disabled={busy}
                              onClick={() => void decideInvitation(invitation, "decline")}
                            >
                              <X size={13} />
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </>
                )}

                {(tab !== "requests") && (
                  <>
                    <div className="nv2-section-label">
                      <span>{tab === "groups" ? "Groups" : tab === "dms" ? "Direct messages" : "Conversations"}</span>
                      <span>{conversationItems.length}</span>
                    </div>
                    {conversationItems.length === 0 ? (
                      <div style={{ padding: "18px 10px", color: "#7f8796", fontSize: 12, lineHeight: 1.6 }}>
                        {query ? "No conversations match that search." : tab === "groups" ? "No groups yet. Create one to start a shared conversation." : "No conversations yet. Connect with a verified Card to start a DM."}
                      </div>
                    ) : conversationItems.map((item) => {
                      const active = item.kind === selectedKind && (item.kind === "dm" ? item.connection.id : item.group.id) === selectedId;
                      const id = item.kind === "dm" ? item.connection.id : item.group.id;
                      const name = item.kind === "dm" ? item.connection.partner.name : item.group.name;
                      const preview = previewText(item.kind === "dm" ? item.connection.last_message_preview : item.group.last_message_preview);
                      const unreadCount = item.kind === "dm" ? item.connection.unread_count ?? 0 : item.group.unread_count ?? 0;
                      const lastAt = item.kind === "dm" ? item.connection.last_message_at : item.group.last_message_at;
                      const mine = !preview.startsWith("AI: ") && (item.kind === "dm"
                        ? item.connection.last_message_sender_user_id === userId
                        : item.group.last_message_sender_user_id === userId);
                      return (
                        <button
                          type="button"
                          key={`${item.kind}-${id}`}
                          className={`nv2-item${active ? " is-active" : ""}`}
                          onClick={() => selectConversation(item.kind, id)}
                          onPointerEnter={() => void prefetchConversation(item.kind, id)}
                        >
                          {item.kind === "dm"
                            ? <Avatar card={item.connection.partner} />
                            : <Avatar name={item.group.name} group />}
                          <span className="nv2-item-main">
                            <span className="nv2-item-top">
                              <span className="nv2-item-name">{name}</span>
                              <span className="nv2-item-time">{relativeTime(lastAt)}</span>
                            </span>
                            <span className="nv2-item-preview">
                              <span>{preview ? `${mine ? "You: " : ""}${preview}` : item.kind === "group" ? item.group.description || "No messages yet" : `@${item.connection.partner.handle || "card"}`}</span>
                              {unreadCount > 0 && <span className="nv2-badge">{unreadCount > 99 ? "99+" : unreadCount}</span>}
                            </span>
                          </span>
                        </button>
                      );
                    })}
                  </>
                )}
              </>
            )}
          </div>
        </aside>

        <section className="nv2-main">
          {selected ? (
            <ConversationPane
              key={`${selected.kind}-${selected.id}`}
              token={token}
              userId={userId}
              conversation={selected}
              members={selectedGroupMembers}
              groupMemoryEnabled={groupMemoryEnabled}
              groupAgentRepliesEnabled={groupAgentRepliesEnabled}
              onBack={() => setMobileOpen(false)}
              onMembersNeeded={loadMembers}
              onInboxActivity={onInboxActivity}
              onConversationRead={onConversationRead}
            />
          ) : (
            <div className="nv2-empty">
              <div className="nv2-empty-icon"><MessageCircle size={28} /></div>
              <h2>{tab === "requests" ? "Connection requests" : "Pick a conversation"}</h2>
              <p>
                {tab === "requests"
                  ? "Accept a request to open a DM. Group invitations become live conversations as soon as you join."
                  : "Direct messages and groups live here. Select a conversation, or start a new group from the plus button."}
              </p>
            </div>
          )}
        </section>
      </div>

      {composer && (
        <ComposerModal
          mode={composer}
          token={token}
          onClose={() => setComposer(null)}
          onNotice={setNotice}
          onCreated={(groupId) => {
            setComposer(null);
            void loadInbox();
            if (groupId) selectConversation("group", groupId);
          }}
        />
      )}
    </main>
  );
}

function ConversationPane({
  token,
  userId,
  conversation,
  members,
  groupMemoryEnabled,
  groupAgentRepliesEnabled,
  onBack,
  onMembersNeeded,
  onInboxActivity,
  onConversationRead,
}: {
  token: string;
  userId: string;
  conversation: NetworkConversation;
  members?: CardGroupMember[];
  groupMemoryEnabled: boolean;
  groupAgentRepliesEnabled: boolean;
  onBack: () => void;
  onMembersNeeded: (groupId: string) => void;
  onInboxActivity: (kind: "dm" | "group", id: string, message: CardMessage, unreadDelta: number) => void;
  onConversationRead: (kind: "dm" | "group", id: string) => void;
}) {
  const isDm = conversation.kind === "dm";
  const conversationId = conversation.id;
  const kind: NetworkThreadKind = isDm ? "dm" : "group";
  const key = threadKey(kind, conversationId);
  const cache = useNetworkCache();
  const cachedThread = cache.threads[key];
  const initialThread = getCachedThread(kind, conversationId);
  const connection = conversation.kind === "dm" ? conversation.connection : null;
  const group = conversation.kind === "group" ? conversation.group : null;
  const [threadId, setThreadId] = useState<string | null>(initialThread?.threadId ?? connection?.thread_id ?? null);
  const [messages, setMessages] = useState<CardMessage[]>(initialThread?.messages ?? []);
  const [loading, setLoading] = useState(!initialThread);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [hasMore, setHasMore] = useState(initialThread?.hasMore ?? false);
  const [latestSeq, setLatestSeq] = useState(initialThread?.latestSeq ?? 0);
  const [draft, setDraft] = useState("");
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionStart, setMentionStart] = useState<number | null>(null);
  const [mentionIndex, setMentionIndex] = useState(0);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [peerReadSeq, setPeerReadSeq] = useState(initialThread?.peerReadSeq ?? 0);
  const [hasNew, setHasNew] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [personQuery, setPersonQuery] = useState("");
  const [people, setPeople] = useState<(CardSummary & { user_id: string })[]>([]);
  const [inviteNotice, setInviteNotice] = useState("");
  const [inviteBusy, setInviteBusy] = useState(false);
  const [memoryOpen, setMemoryOpen] = useState(false);
  const [memory, setMemory] = useState<CardGroupMemoryList | null>(null);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memoryError, setMemoryError] = useState("");
  const [memoryQuery, setMemoryQuery] = useState("");
  const [memoryResults, setMemoryResults] = useState<CardGroupMemory[] | null>(null);
  const [remembering, setRemembering] = useState<string | null>(null);
  const [typingAgents, setTypingAgents] = useState<Record<string, "pending" | "running">>({});
  const [agentErrors, setAgentErrors] = useState<Record<string, string>>({});
  const [agentPreference, setAgentPreference] = useState<CardAgentPreference | null>(null);
  const [agentPreferenceBusy, setAgentPreferenceBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const atBottomRef = useRef(true);
  const lastMarkedRef = useRef(0);
  const readTimer = useRef<number | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const typingTimers = useRef<Record<string, number>>({});

  const rememberIntent = !isDm && groupMemoryEnabled && /^\s*remember\b/i.test(draft);
  const mentionSuggestions = useMemo(() => {
    if (isDm || mentionQuery === null) return [];
    const query = mentionQuery.trim().toLowerCase();
    return (members ?? [])
      .filter((member) => member.user_id !== userId && member.card?.handle)
      .filter((member) => {
        if (!query) return true;
        return (member.card?.handle || "").toLowerCase().includes(query)
          || (member.card?.name || "").toLowerCase().includes(query);
      })
      .slice(0, 6);
  }, [isDm, members, mentionQuery, userId]);

  const syncMention = useCallback((value: string, caret: number) => {
    const mention = activeMention(value, caret);
    setMentionQuery(mention?.query ?? null);
    setMentionStart(mention?.start ?? null);
    setMentionIndex(0);
  }, []);

  const chooseMention = useCallback((member: CardGroupMember) => {
    const handle = member.card?.handle;
    if (!handle || mentionStart == null) return;
    const textarea = textareaRef.current;
    const caret = textarea?.selectionStart ?? draft.length;
    const next = `${draft.slice(0, mentionStart)}@${handle} ${draft.slice(caret)}`;
    const cursor = mentionStart + handle.length + 2;
    setDraft(next);
    setMentionQuery(null);
    setMentionStart(null);
    setMentionIndex(0);
    window.requestAnimationFrame(() => {
      const element = textareaRef.current;
      if (!element) return;
      element.focus();
      element.setSelectionRange(cursor, cursor);
      element.style.height = "auto";
      element.style.height = `${Math.min(element.scrollHeight, 150)}px`;
    });
  }, [draft, mentionStart]);

  useEffect(() => {
    if (group) onMembersNeeded(group.id);
  }, [group, onMembersNeeded]);

  useEffect(() => {
    if (!group || !groupAgentRepliesEnabled) return;
    let cancelled = false;
    fetchAgentPreference(token)
      .then((value) => { if (!cancelled) setAgentPreference(value); })
      .catch(() => { if (!cancelled) setAgentPreference({ enabled: true }); });
    return () => { cancelled = true; };
  }, [group, groupAgentRepliesEnabled, token]);

  useEffect(() => {
    if (!group || !groupMemoryEnabled || !memoryOpen) return;
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMemoryLoading(true);
    setMemoryError("");
    fetchGroupMemory(token, group.id, controller.signal)
      .then((value) => { if (!controller.signal.aborted) setMemory(value); })
      .catch((failure) => { if (!controller.signal.aborted) setMemoryError(failure instanceof Error ? failure.message : "Could not load group memory"); })
      .finally(() => { if (!controller.signal.aborted) setMemoryLoading(false); });
    return () => controller.abort();
  }, [group, groupMemoryEnabled, memoryOpen, token]);

  useEffect(() => () => {
    for (const timer of Object.values(typingTimers.current)) window.clearTimeout(timer);
  }, []);

  const markTyping = useCallback((userId: string, status: "pending" | "running" | "done" | "failed") => {
    if (typingTimers.current[userId]) {
      window.clearTimeout(typingTimers.current[userId]);
      delete typingTimers.current[userId];
    }
    if (status === "pending" || status === "running") {
      setTypingAgents((current) => ({ ...current, [userId]: status }));
      setAgentErrors((current) => {
        if (!(userId in current)) return current;
        const next = { ...current };
        delete next[userId];
        return next;
      });
      typingTimers.current[userId] = window.setTimeout(() => {
        setTypingAgents((current) => {
          if (!(userId in current)) return current;
          const next = { ...current };
          delete next[userId];
          return next;
        });
        delete typingTimers.current[userId];
      }, 90_000);
    } else {
      setTypingAgents((current) => {
        if (!(userId in current)) return current;
        const next = { ...current };
        delete next[userId];
        return next;
      });
      if (status === "failed") {
        setAgentErrors((current) => ({ ...current, [userId]: "The assistant couldn't reply. Try tagging again." }));
      }
    }
  }, []);

  // A prefetch (or a second tab) can fill the cache while this pane is open.
  useEffect(() => {
    if (!cachedThread) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMessages((current) => mergeMessages(current, cachedThread.messages));
    setLatestSeq((current) => Math.max(current, cachedThread.latestSeq));
    setPeerReadSeq((current) => Math.max(current, cachedThread.peerReadSeq));
    if (cachedThread.threadId) setThreadId(cachedThread.threadId);
  }, [cachedThread]);

  const load = useCallback(async (signal?: AbortSignal, afterSeq = 0) => {
    if (!afterSeq) setLoading(true);
    setError("");
    try {
      const fetchPage = (options: { afterSeq?: number; beforeSeq?: number }) => isDm
        ? fetchDmMessages(token, conversationId, { limit: 40, signal, ...options })
        : fetchGroupMessages(token, conversationId, { limit: 40, signal, ...options });
      let page = await fetchPage({ afterSeq: afterSeq || undefined });
      if (signal?.aborted) return;

      // A cached conversation can be far behind. The server returns the
      // newest page after the cursor, so walk backwards to close the gap
      // instead of silently dropping the middle of the conversation.
      if (afterSeq && page.has_more) {
        let messages = page.messages;
        let oldest = messages[0]?.seq;
        let more: boolean = page.has_more;
        for (let round = 0; round < 3 && more && oldest != null && oldest > afterSeq; round += 1) {
          const older = await fetchPage({ beforeSeq: oldest });
          if (signal?.aborted) return;
          messages = mergeMessages(older.messages, messages);
          more = older.has_more;
          oldest = messages[0]?.seq;
        }
        page = { ...page, messages };
      }

      setMessages((current) => mergeMessages(current, page.messages));
      if (!afterSeq) setHasMore(page.has_more);
      setLatestSeq((current) => Math.max(current, page.latest_seq));
      if (page.peer_last_read_seq != null) setPeerReadSeq((current) => Math.max(current, page.peer_last_read_seq ?? 0));
      if (page.thread_id) setThreadId(page.thread_id);
      cacheThreadPage(kind, conversationId, page, afterSeq ? "newer" : "initial");
    } catch (failure) {
      if (!signal?.aborted) setError(failure instanceof Error ? failure.message : "Could not load messages");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [conversationId, isDm, kind, token]);

  useEffect(() => {
    const controller = new AbortController();
    // The pane is keyed by conversation. Seed from the cache first, then fetch
    // only what changed; the skeleton is reserved for a truly cold thread.
    const cached = getCachedThread(kind, conversationId);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMessages(cached?.messages ?? []);
    setDraft("");
    setHasMore(cached?.hasMore ?? false);
    setLatestSeq(cached?.latestSeq ?? 0);
    setPeerReadSeq(cached?.peerReadSeq ?? 0);
    setThreadId(cached?.threadId ?? connection?.thread_id ?? null);
    setLoading(!cached);
    setHasNew(false);
    setInviteOpen(false);
    setPeople([]);
    setPersonQuery("");
    setInviteNotice("");
    lastMarkedRef.current = 0;
    void load(controller.signal, cached?.latestSeq ?? 0);
    return () => controller.abort();
  }, [connection?.thread_id, conversationId, kind, load]);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "smooth") => {
    window.requestAnimationFrame(() => {
      const element = scrollRef.current;
      if (element) element.scrollTo({ top: element.scrollHeight, behavior });
    });
    atBottomRef.current = true;
    setHasNew(false);
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!loading) scrollToBottom("auto");
  }, [loading, scrollToBottom]);

  const scheduleRead = useCallback((seq: number) => {
    if (!seq || seq <= lastMarkedRef.current) return;
    if (readTimer.current) window.clearTimeout(readTimer.current);
    readTimer.current = window.setTimeout(() => {
      void markNetworkRead(token, isDm ? "dm" : "group", conversationId, seq)
        .then(() => {
          lastMarkedRef.current = Math.max(lastMarkedRef.current, seq);
          onConversationRead(isDm ? "dm" : "group", conversationId);
        })
        .catch(() => { /* a later focus or message retries */ });
    }, 350);
  }, [conversationId, isDm, onConversationRead, token]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible" && document.hasFocus() && latestSeq > 0) {
        scheduleRead(latestSeq);
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
      if (readTimer.current) window.clearTimeout(readTimer.current);
    };
  }, [latestSeq, scheduleRead]);

  useEffect(() => {
    if (!loading && latestSeq > 0 && document.visibilityState === "visible" && document.hasFocus()) {
      scheduleRead(latestSeq);
    }
  }, [latestSeq, loading, scheduleRead]);

  const markRemembered = useCallback((messageId: string, memoryId: string) => {
    setMessages((current) => current.map((message) => message.id === messageId
      ? { ...message, remembered: true, memory_id: memoryId }
      : message));
    markCachedMessageRemembered(kind, conversationId, messageId, memoryId);
  }, [conversationId, kind]);

  const handleRealtime = useCallback((event: NetworkRealtimeEvent) => {
    if (event.event === "message") {
      const message = asMessage(event.payload.message);
      if (!message) return;
      setMessages((current) => mergeMessages(current, [message]));
      setLatestSeq((current) => Math.max(current, message.seq ?? 0));
      cacheThreadMessage(kind, conversationId, message);
      if (isAgentMessage(message) && message.agent_for_user_id) {
        markTyping(message.agent_for_user_id, "done");
        setAgentErrors((current) => {
          if (!(message.agent_for_user_id! in current)) return current;
          const next = { ...current };
          delete next[message.agent_for_user_id!];
          return next;
        });
      }
      const visible = document.visibilityState === "visible" && document.hasFocus();
      const mine = message.sender_user_id === userId;
      onInboxActivity(isDm ? "dm" : "group", conversationId, message, mine ? 0 : visible ? 0 : 1);
      if (!mine && visible) scheduleRead(message.seq ?? 0);
      if (atBottomRef.current) scrollToBottom("smooth");
      else setHasNew(true);
    } else if (event.event === "read") {
      if (event.payload.user_id !== userId) {
        const seq = Number(event.payload.last_read_seq) || 0;
        setPeerReadSeq((current) => Math.max(current, seq));
        cacheThreadPeerRead(kind, conversationId, seq);
      }
    } else if (event.event === "memory") {
      if (event.payload.kind === "group_memory_link") {
        const messageId = String(event.payload.message_id || "");
        const memoryId = String(event.payload.memory_id || "");
        if (messageId && memoryId) markRemembered(messageId, memoryId);
      }
      if (memoryOpen && event.payload.kind === "group_memory") {
        const content = String(event.payload.content || "");
        const memoryKind = String(event.payload.memory_kind || "");
        if (content && memoryKind === "summary") {
          setMemory((current) => current ? { ...current, summary: { ...(current.summary || { id: "", kind: "summary", content }), content } } : current);
        } else if (content && memoryKind === "fact") {
          setMemory((current) => current ? { ...current, facts: current.facts.some((fact) => fact.content === content) ? current.facts : [{ id: String(event.payload.memory_id || ""), kind: "fact", content }, ...current.facts] } : current);
        }
      }
    } else if (event.event === "agent_typing") {
      const target = String(event.payload.user_id || "");
      const status = String(event.payload.status || "");
      if (target && ["pending", "running", "done", "failed"].includes(status)) {
        markTyping(target, status as "pending" | "running" | "done" | "failed");
      }
    }
  }, [conversationId, isDm, kind, markRemembered, markTyping, memoryOpen, onInboxActivity, scheduleRead, scrollToBottom, userId]);

  useNetworkRealtime({
    token,
    topic: isDm ? (threadId ? `cards:dm:${threadId}` : null) : `cards:group:${conversationId}`,
    events: ["message", "read", "memory", "agent_typing"],
    onEvent: handleRealtime,
    onReconnect: () => void load(undefined, latestSeq),
  });

  useEffect(() => {
    const timer = window.setInterval(async () => {
      if (document.visibilityState !== "visible") return;
      try {
        const page = isDm
          ? await fetchDmMessages(token, conversationId, { limit: 40, afterSeq: latestSeq || undefined })
          : await fetchGroupMessages(token, conversationId, { limit: 40, afterSeq: latestSeq || undefined });
        if (page.messages.length > 0) {
          setMessages((current) => mergeMessages(current, page.messages));
          setLatestSeq((current) => Math.max(current, page.latest_seq));
          if (page.peer_last_read_seq != null) setPeerReadSeq((current) => Math.max(current, page.peer_last_read_seq ?? 0));
          cacheThreadPage(kind, conversationId, page, "newer");
          onInboxActivity(isDm ? "dm" : "group", conversationId, page.messages[page.messages.length - 1], 0);
          if (atBottomRef.current) scrollToBottom("smooth");
          else setHasNew(true);
        }
      } catch {
        // Realtime is primary; the fallback will try again.
      }
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [conversationId, isDm, kind, latestSeq, onInboxActivity, scrollToBottom, token]);

  function onScroll() {
    const element = scrollRef.current;
    if (!element) return;
    const nearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 120;
    atBottomRef.current = nearBottom;
    if (nearBottom && hasNew) setHasNew(false);
    if (element.scrollTop < 80) void loadOlder();
  }

  async function loadOlder() {
    if (loadingOlder || !hasMore) return;
    const firstSeq = messages.find((message) => message.seq != null)?.seq;
    if (!firstSeq) return;
    const element = scrollRef.current;
    const previousHeight = element?.scrollHeight ?? 0;
    setLoadingOlder(true);
    try {
      const page = isDm
        ? await fetchDmMessages(token, conversationId, { limit: 40, beforeSeq: firstSeq })
        : await fetchGroupMessages(token, conversationId, { limit: 40, beforeSeq: firstSeq });
      setMessages((current) => mergeMessages(page.messages, current));
      setHasMore(page.has_more);
      cacheThreadPage(kind, conversationId, page, "older");
      window.requestAnimationFrame(() => {
        if (element) element.scrollTop = element.scrollHeight - previousHeight;
      });
    } catch {
      setError("Could not load older messages");
    } finally {
      setLoadingOlder(false);
    }
  }

  async function send() {
    const content = draft.trim();
    if (!content || sending) return;
    const rememberAfterSend = rememberIntent;
    const clientId = newClientId();
    const optimistic: CardMessage = {
      id: clientId,
      client_id: clientId,
      sender_user_id: userId,
      content,
      created_at: new Date().toISOString(),
      pending: true,
    };
    setMessages((current) => mergeMessages(current, [optimistic]));
    cacheThreadMessage(kind, conversationId, optimistic);
    setDraft("");
    setMentionQuery(null);
    setMentionStart(null);
    setMentionIndex(0);
    setSending(true);
    setError("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    scrollToBottom("smooth");
    try {
      const result = isDm
        ? await sendDm(token, conversationId, content, clientId)
        : await sendGroupMessage(token, conversationId, content, clientId);
      setMessages((current) => mergeMessages(current, [result.message]));
      setLatestSeq((current) => Math.max(current, result.message.seq ?? current));
      cacheThreadMessage(kind, conversationId, result.message);
      onInboxActivity(isDm ? "dm" : "group", conversationId, result.message, 0);
      if (!isDm && result.agent_replies) {
        const handles = new Set(Array.from(content.matchAll(/(?<![\w.])@([A-Za-z0-9_.-]{1,64})/g), (match) => match[1].toLowerCase()));
        for (const member of members ?? []) {
          const handle = member.card?.handle?.toLowerCase();
          if (handle && handles.has(handle)) markTyping(member.user_id, "pending");
        }
      }
      if (rememberAfterSend && !isDm) {
        try {
          const saved = await rememberGroupMessage(token, conversationId, result.message.id);
          markRemembered(result.message.id, saved.memory.id);
        } catch (failure) {
          setError(failure instanceof Error ? failure.message : "Message sent, but could not save it to group memory");
        }
      }
    } catch (failure) {
      setMessages((current) => current.filter((message) => message.client_id !== clientId));
      removeCachedMessage(kind, conversationId, clientId);
      setDraft((current) => current || content);
      setError(failure instanceof Error ? failure.message : "Message failed");
    } finally {
      setSending(false);
    }
  }

  async function remember(message: CardMessage) {
    if (!group || remembering || isAgentMessage(message)) return;
    setRemembering(message.id);
    setMemoryError("");
    try {
      const result = await rememberGroupMessage(token, group.id, message.id);
      markRemembered(message.id, result.memory.id);
      setMemory((current) => current
        ? { ...current, facts: current.facts.some((fact) => fact.id === result.memory.id) ? current.facts : [result.memory, ...current.facts] }
        : current);
    } catch (failure) {
      setMemoryError(failure instanceof Error ? failure.message : "Could not save to group memory");
    } finally {
      setRemembering(null);
    }
  }

  async function searchMemory() {
    if (!group) return;
    const query = memoryQuery.trim();
    if (!query) {
      setMemoryResults(null);
      return;
    }
    setMemoryLoading(true);
    setMemoryError("");
    try {
      const result = await searchGroupMemory(token, group.id, query);
      setMemoryResults(result.results);
    } catch (failure) {
      setMemoryError(failure instanceof Error ? failure.message : "Could not search group memory");
    } finally {
      setMemoryLoading(false);
    }
  }

  async function toggleAgentPreference() {
    if (agentPreferenceBusy) return;
    setAgentPreferenceBusy(true);
    try {
      const next = !(agentPreference?.enabled ?? true);
      const result = await saveAgentPreference(token, next);
      setAgentPreference(result);
    } catch (failure) {
      setMemoryError(failure instanceof Error ? failure.message : "Could not update agent replies");
    } finally {
      setAgentPreferenceBusy(false);
    }
  }

  async function searchPeople() {
    if (!group || group.my_role !== "owner") return;
    setInviteBusy(true);
    setInviteNotice("");
    try {
      const result = await cardsNetworkRequest<{ people: (CardSummary & { user_id: string })[] }>(
        `/groups/${group.id}/people?query=${encodeURIComponent(personQuery)}`, token,
      );
      setPeople(result.people);
    } catch (failure) {
      setInviteNotice(failure instanceof Error ? failure.message : "Could not search connections");
    } finally {
      setInviteBusy(false);
    }
  }

  async function invite(handle: string) {
    if (!group) return;
    setInviteBusy(true);
    setInviteNotice("");
    try {
      await cardsNetworkRequest(`/groups/${group.id}/invitations`, token, "POST", { target_handle: handle });
      setPeople([]);
      setPersonQuery("");
      setInviteNotice("Invitation sent");
    } catch (failure) {
      setInviteNotice(failure instanceof Error ? failure.message : "Could not send invitation");
    } finally {
      setInviteBusy(false);
    }
  }

  const memberByUser = useMemo(() => new Map((members ?? []).map((member) => [member.user_id, member])), [members]);
  const grouped = useMemo(() => {
    const result: { key: string; label: string; messages: CardMessage[] }[] = [];
    for (const message of messages) {
      const key = dayKey(message.created_at);
      const last = result[result.length - 1];
      if (!last || last.key !== key) result.push({ key, label: dayLabel(message.created_at), messages: [message] });
      else last.messages.push(message);
    }
    return result;
  }, [messages]);

  const title = isDm ? connection?.partner.name || "Direct message" : group?.name || "Group";
  const subtitle = isDm
    ? `@${connection?.partner.handle || "card"}`
    : `${members?.length ?? 0} member${(members?.length ?? 0) === 1 ? "" : "s"}${group?.description ? ` · ${group.description}` : ""}`;

  return (
    <>
      <header className="nv2-conv-head">
        <button type="button" className="nv2-icon-button nv2-back" aria-label="Back to conversations" onClick={onBack}>
          <ArrowLeft size={18} />
        </button>
        {isDm
          ? <Avatar card={connection?.partner} size={40} />
          : <Avatar name={group?.name} group size={40} />}
        <div className="nv2-conv-title">
          <strong>{title}</strong>
          <small>{subtitle}</small>
        </div>
        {!isDm && (members?.length ?? 0) > 0 && (
          <div className="nv2-member-strip" aria-label="Group members">
            {members!.slice(0, 5).map((member) => (
              <Avatar key={member.id} card={member.card} name={member.card?.name || member.user_id} size={26} small />
            ))}
          </div>
        )}
        {!isDm && groupMemoryEnabled && (
          <button
            type="button"
            className={`nv2-icon-button${memoryOpen ? " is-active" : ""}`}
            aria-label="Group memory"
            aria-pressed={memoryOpen}
            onClick={() => setMemoryOpen((current) => !current)}
          >
            <Brain size={17} />
          </button>
        )}
        {!isDm && group?.my_role === "owner" && (
          <button
            type="button"
            className="nv2-icon-button"
            aria-label="Invite people to group"
            onClick={() => setInviteOpen((current) => !current)}
          >
            <Plus size={17} />
          </button>
        )}
      </header>

      {!isDm && groupMemoryEnabled && memoryOpen && group && (
        <section className="nv2-memory-panel" aria-label="Group memory">
          <div className="nv2-memory-head">
            <div>
              <span className="nv2-eyebrow">Saved context</span>
              <strong>Group memory</strong>
            </div>
            <button type="button" className="nv2-icon-button" aria-label="Close group memory" onClick={() => setMemoryOpen(false)}>
              <X size={15} />
            </button>
          </div>
          <p className="nv2-memory-note">
            Recent messages are sent to the assistant as-is. Longer-term context is kept as a rolling summary and durable facts.
          </p>
          <div className="nv2-memory-search">
            <Search size={14} />
            <input
              value={memoryQuery}
              onChange={(event) => {
                setMemoryQuery(event.target.value);
                if (!event.target.value.trim()) setMemoryResults(null);
              }}
              onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void searchMemory(); } }}
              placeholder="Search group memory by meaning"
              aria-label="Search group memory"
              maxLength={300}
            />
            <button type="button" className="nv2-small-button" onClick={() => void searchMemory()} disabled={memoryLoading}>
              {memoryLoading ? <Loader2 size={13} className="nv2-spin" /> : "Search"}
            </button>
          </div>
          {memoryError && <p className="nv2-error" role="alert">{memoryError}</p>}
          {memory?.summary && (
            <div className="nv2-memory-summary">
              <span className="nv2-memory-kind"><Sparkles size={12} /> Summary</span>
              <p>{memory.summary.content}</p>
            </div>
          )}
          <div className="nv2-memory-facts">
            <span className="nv2-memory-kind"><Bookmark size={12} /> {memoryResults ? "Search results" : "Facts"}</span>
            {(memoryResults ?? memory?.facts ?? []).length === 0 ? (
              <p className="nv2-memory-empty">
                No saved facts yet. Use the bookmark on a message to remember it, or let the assistant summarize the conversation.
              </p>
            ) : (
              (memoryResults ?? memory?.facts ?? []).map((fact) => (
                <div className="nv2-memory-fact" key={fact.id}>
                  <span>{fact.content}</span>
                  {typeof fact.similarity === "number" && <small>{Math.round(fact.similarity * 100)}% match</small>}
                </div>
              ))
            )}
          </div>
          {groupAgentRepliesEnabled && (
            <label className="nv2-agent-toggle">
              <input
                type="checkbox"
                checked={agentPreference?.enabled ?? true}
                disabled={agentPreferenceBusy}
                onChange={() => void toggleAgentPreference()}
              />
              Let my Card assistant reply when someone tags me in a group
            </label>
          )}
        </section>
      )}

      <div className="nv2-messages" ref={scrollRef} onScroll={onScroll} aria-label={isDm ? "Direct messages" : "Group messages"}>
        {loading ? (
          <>
            <div className="nv2-skeleton" style={{ width: "55%", alignSelf: "flex-start" }} />
            <div className="nv2-skeleton" style={{ width: "42%", alignSelf: "flex-end" }} />
            <div className="nv2-skeleton" style={{ width: "60%", alignSelf: "flex-start" }} />
          </>
        ) : messages.length === 0 ? (
          <div className="nv2-empty" style={{ flex: 1 }}>
            <div className="nv2-empty-icon"><MessageCircle size={26} /></div>
            <h2>No messages yet</h2>
            <p>{isDm ? `Say hello to ${connection?.partner.name || "your connection"}.` : "Start the conversation with your group."}</p>
          </div>
        ) : (
          <>
            {hasMore && (
              <button type="button" className="nv2-load-older" disabled={loadingOlder} onClick={() => void loadOlder()}>
                {loadingOlder ? "Loading…" : "Load older messages"}
              </button>
            )}
            {grouped.map((day) => (
              <div key={day.key} style={{ display: "contents" }}>
                <div className="nv2-day">{day.label}</div>
                {day.messages.map((message) => {
                  const agent = isAgentMessage(message);
                  const mine = !agent && message.sender_user_id === userId;
                  const sender = memberByUser.get(message.sender_user_id);
                  const senderName = agent
                    ? `AI assistant for ${sender?.card?.name || "Member"}`
                    : sender?.card?.name || "Member";
                  return (
                    <div
                      key={message.client_id ?? message.id}
                      className={`nv2-msg-row${mine ? " is-mine" : ""}${agent ? " is-agent" : ""}`}
                    >
                      {!mine && (
                        agent ? (
                          <span className="nv2-agent-avatar" aria-hidden="true"><Bot size={14} /></span>
                        ) : (
                          <Avatar
                            card={isDm ? connection?.partner : sender?.card}
                            name={isDm ? connection?.partner.name : sender?.card?.name || "Member"}
                            size={26}
                            small
                          />
                        )
                      )}
                      <div className="nv2-msg-stack">
                        {!mine && !isDm && (
                          <div className={`nv2-msg-sender${agent ? " is-agent" : ""}`}>
                            {agent && <Bot size={11} />}
                            {senderName}
                            {agent && sender?.card?.handle && <span className="nv2-agent-handle">@{sender.card.handle}</span>}
                          </div>
                        )}
                        <div className={`nv2-bubble${message.pending ? " is-pending" : ""}${agent ? " is-agent" : ""}${message.remembered ? " is-remembered" : ""}`}>
                          {renderMessageContent(message.content)}
                        </div>
                        <div className="nv2-msg-meta">
                          <span>{formatTime(message.created_at)}</span>
                          {message.pending && <span>Sending…</span>}
                          {!isDm && message.remembered && (
                            <span className="nv2-remembered-badge"><BookmarkCheck size={10} /> Saved to memory</span>
                          )}
                          {!isDm && groupMemoryEnabled && !agent && !message.pending && !message.remembered && (
                            <button
                              type="button"
                              className="nv2-remember-button"
                              aria-label="Save message to group memory"
                              title="Remember this"
                              disabled={remembering === message.id}
                              onClick={() => void remember(message)}
                            >
                              {remembering === message.id ? <Loader2 size={11} className="nv2-spin" /> : <Bookmark size={11} />}
                              Remember
                            </button>
                          )}
                          {mine && isDm && !message.pending && (message.seq ?? 0) > 0 && peerReadSeq >= (message.seq ?? 0) && (
                            <span className="nv2-seen">Seen</span>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ))}
            {Object.entries(typingAgents).map(([agentUserId]) => {
              const member = memberByUser.get(agentUserId);
              const name = member?.card?.name || "a group member";
              const handle = member?.card?.handle;
              return (
                <div className="nv2-typing-row" key={`typing-${agentUserId}`} aria-live="polite">
                  <span className="nv2-agent-avatar" aria-hidden="true"><Bot size={14} /></span>
                  <span>
                    AI assistant for {name}{handle ? ` (@${handle})` : ""}
                    <span className="nv2-typing-dots" aria-label="is thinking"><i /><i /><i /></span>
                  </span>
                </div>
              );
            })}
            {Object.entries(agentErrors).map(([agentUserId, message]) => {
              const member = memberByUser.get(agentUserId);
              return (
                <div className="nv2-agent-error" key={`agent-error-${agentUserId}`} role="status">
                  <Bot size={12} /> {message}{member?.card?.handle ? ` (@${member.card.handle})` : ""}
                </div>
              );
            })}
            {hasNew && (
              <button type="button" className="nv2-new-pill" onClick={() => scrollToBottom("smooth")}>
                New messages ↓
              </button>
            )}
          </>
        )}
      </div>

      <div className="nv2-composer">
        {error && <p className="nv2-error" role="alert">{error}</p>}
        {inviteOpen && group && (
          <div className="nv2-invite-panel">
            <div style={{ display: "flex", gap: 8, marginBottom: 6 }}>
              <input
                className="nv2-field"
                style={{ margin: 0 }}
                value={personQuery}
                onChange={(event) => setPersonQuery(event.target.value)}
                onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void searchPeople(); } }}
                placeholder="Search connected Cards to invite"
                aria-label="Search connected Cards"
                maxLength={120}
              />
              <button type="button" className="nv2-small-button" aria-label="Search people to invite" disabled={inviteBusy} onClick={() => void searchPeople()}>
                <Search size={14} />
              </button>
            </div>
            {inviteNotice && <p style={{ margin: "4px 0", color: "#a5b4fc", fontSize: 11.5 }}>{inviteNotice}</p>}
            {people.map((person) => (
              <div className="nv2-invite-row" key={person.user_id}>
                <Avatar card={person} size={28} small />
                <span>{person.name} <small style={{ color: "#7f8796" }}>@{person.handle}</small></span>
                <button type="button" className="nv2-small-button" disabled={inviteBusy} onClick={() => void invite(person.handle || "")}>
                  Invite
                </button>
              </div>
            ))}
          </div>
        )}
        {!isDm && mentionQuery !== null && (
          <div className="nv2-mention-menu" role="listbox" aria-label="Tag a group member">
            {members === undefined ? (
              <div className="nv2-mention-empty">Loading group members…</div>
            ) : mentionSuggestions.length === 0 ? (
              <div className="nv2-mention-empty">No matching member. Try a Card handle.</div>
            ) : mentionSuggestions.map((member, index) => (
              <button
                type="button"
                role="option"
                aria-selected={index === mentionIndex}
                key={member.id}
                className={`nv2-mention-option${index === mentionIndex ? " is-active" : ""}`}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => chooseMention(member)}
              >
                <Avatar card={member.card} name={member.card?.name || "Member"} size={26} small />
                <span className="nv2-mention-name">{member.card?.name || "Member"}</span>
                <span className="nv2-mention-handle">@{member.card?.handle}</span>
              </button>
            ))}
          </div>
        )}
        {rememberIntent && (
          <div className="nv2-remember-intent" role="status">
            <BookmarkCheck size={12} /> This message will be saved to group memory
          </div>
        )}
        <div className={`nv2-composer-box${rememberIntent ? " is-remember-intent" : ""}`}>
          <textarea
            ref={textareaRef}
            className="nv2-textarea"
            value={draft}
            onChange={(event) => {
              const value = event.target.value;
              setDraft(value);
              syncMention(value, event.target.selectionStart ?? value.length);
              event.target.style.height = "auto";
              event.target.style.height = `${Math.min(event.target.scrollHeight, 150)}px`;
            }}
            onSelect={(event) => syncMention(event.currentTarget.value, event.currentTarget.selectionStart ?? 0)}
            onKeyDown={(event) => {
              if (mentionQuery !== null && mentionSuggestions.length > 0) {
                if (event.key === "ArrowDown") {
                  event.preventDefault();
                  setMentionIndex((current) => (current + 1) % mentionSuggestions.length);
                  return;
                }
                if (event.key === "ArrowUp") {
                  event.preventDefault();
                  setMentionIndex((current) => (current - 1 + mentionSuggestions.length) % mentionSuggestions.length);
                  return;
                }
                if (event.key === "Enter" || event.key === "Tab") {
                  event.preventDefault();
                  chooseMention(mentionSuggestions[mentionIndex] ?? mentionSuggestions[0]);
                  return;
                }
                if (event.key === "Escape") {
                  event.preventDefault();
                  setMentionQuery(null);
                  setMentionStart(null);
                  return;
                }
              }
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                void send();
              }
            }}
            placeholder={isDm ? `Message ${connection?.partner.name || ""}` : "Message the group — @handle to ask their assistant"}
            aria-label={isDm ? "Direct message" : "Group message"}
            maxLength={4000}
            rows={1}
          />
          <button
            type="button"
            className="nv2-send"
            aria-label={isDm ? "Send direct message" : "Send group message"}
            disabled={!draft.trim() || sending}
            onClick={() => void send()}
          >
            <Send size={16} />
          </button>
        </div>
      </div>
    </>
  );
}

function ComposerModal({
  mode,
  token,
  onClose,
  onNotice,
  onCreated,
}: {
  mode: "connection" | "group";
  token: string;
  onClose: () => void;
  onNotice: (notice: string) => void;
  onCreated: (groupId?: string) => void;
}) {
  const [handle, setHandle] = useState("");
  const [requestMessage, setRequestMessage] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      if (mode === "connection") {
        const result = await cardsNetworkRequest<{ connection: CardConnection; existing: boolean }>(
          "/connections", token, "POST", { target_handle: handle.trim(), message: requestMessage },
        );
        onNotice(connectionRequestNotice(result));
        onCreated();
      } else {
        const result = await cardsNetworkRequest<{ group: CardGroup }>(
          "/groups", token, "POST", { name, description, visibility: "private" },
        );
        onNotice("Group created");
        onCreated(result.group.id);
      }
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="nv2-modal-backdrop" role="dialog" aria-modal="true" aria-label={mode === "connection" ? "New connection" : "New group"}>
      <div className="nv2-modal">
        <div className="nv2-modal-head">
          <div>
            <h2>{mode === "connection" ? "Start a connection" : "Create a group"}</h2>
            <p>{mode === "connection" ? "Use the recipient's verified Card handle. DMs open after they accept." : "Small private groups work best. Invitees choose whether to join."}</p>
          </div>
          <button type="button" className="nv2-icon-button" aria-label="Close" onClick={onClose}>
            <X size={16} />
          </button>
        </div>
        {mode === "connection" ? (
          <>
            <input
              className="nv2-field"
              value={handle}
              onChange={(event) => setHandle(event.target.value)}
              placeholder="Card handle, e.g. alice"
              aria-label="Card handle"
              maxLength={128}
            />
            <textarea
              className="nv2-field"
              value={requestMessage}
              onChange={(event) => setRequestMessage(event.target.value)}
              placeholder="Optional note"
              aria-label="Connection note"
              maxLength={2000}
              rows={3}
            />
            <button type="button" className="nv2-primary" disabled={busy || !handle.trim()} onClick={() => void submit()}>
              <Send size={15} /> {busy ? "Sending…" : "Send request"}
            </button>
          </>
        ) : (
          <>
            <input
              className="nv2-field"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Group name"
              aria-label="Group name"
              maxLength={80}
            />
            <textarea
              className="nv2-field"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="What is this group for?"
              aria-label="Group description"
              maxLength={500}
              rows={3}
            />
            <button type="button" className="nv2-primary" disabled={busy || !name.trim()} onClick={() => void submit()}>
              <Plus size={15} /> {busy ? "Creating…" : "Create group"}
            </button>
          </>
        )}
        {error && <p className="nv2-error" role="alert" style={{ marginTop: 10 }}>{error}</p>}
      </div>
    </div>
  );
}
