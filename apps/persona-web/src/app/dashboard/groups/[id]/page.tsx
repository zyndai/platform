"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  Settings as SettingsIcon,
  Send,
  Users,
  Lock,
  Globe2,
  MoreHorizontal,
  Copy,
  Check,
  Trash2,
} from "lucide-react";
import { Avatar, Button } from "@/components/ui";
import { useDashboard } from "@/contexts/DashboardContext";
import { apiDelete, apiGet, apiPatch, apiPost, invalidate } from "@/lib/api";
import { getSupabase } from "@/lib/supabase";

interface Group {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  avatar_url: string | null;
  visibility: "private" | "open";
  owner_user_id: string;
  archived_at: string | null;
  invite_token: string | null;
}

interface Member {
  user_id: string;
  agent_id: string | null;
  role: "owner" | "admin" | "member";
  permissions: Record<string, boolean>;
  joined_at: string;
  display_name: string;
  avatar_url: string | null;
}

interface Message {
  id: string;
  group_id: string;
  sender_user_id: string | null;
  sender_agent_id: string | null;
  sender_name: string | null;
  channel: "human" | "agent" | "system" | "broadcast";
  content: string;
  reply_to: string | null;
  created_at: string;
}

export default function GroupChatPage() {
  const params = useParams<{ id: string }>();
  const groupId = params?.id;
  const { user } = useDashboard();
  const router = useRouter();

  const [group, setGroup] = useState<Group | null>(null);
  const [memberCount, setMemberCount] = useState(0);
  const [members, setMembers] = useState<Member[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // ── @-mention autocomplete state ──────────────────────────────────
  // mentionQuery is the text after the trigger `@`, or null when no
  // mention is in flight. mentionStart is the index of the `@` in the
  // textarea so we know what to replace when the user picks one.
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionStart, setMentionStart] = useState<number>(0);
  const [mentionIndex, setMentionIndex] = useState(0);

  // ── "X's persona is replying…" indicator ──────────────────────────
  // After a successful POST, the backend returns mentioned_user_ids. We
  // park each one here with an expiry so the realtime arrival of the
  // persona's `channel='agent'` row (or a 60s timeout) clears it.
  const [pendingReplies, setPendingReplies] = useState<
    Array<{ userId: string; expiresAt: number }>
  >([]);

  const myMembership = useMemo(
    () => members.find((m) => m.user_id === user?.id) ?? null,
    [members, user?.id],
  );
  const canPost = (myMembership?.permissions?.can_post ?? true) !== false;
  const isManager = myMembership?.role === "owner" || myMembership?.role === "admin";
  const isOwner = myMembership?.role === "owner";

  // ── Mention helpers ─────────────────────────────────────────────
  // Filtered roster suggestions for the current `@…` query, ranked by:
  // exact-prefix match first, then case-insensitive substring match.
  // Self is excluded so a user can't @ themselves into a reply loop.
  const mentionSuggestions = useMemo(() => {
    if (mentionQuery === null) return [];
    const q = mentionQuery.trim().toLowerCase();
    const pool = members.filter((m) => m.user_id !== user?.id && m.agent_id);
    if (!q) return pool.slice(0, 6);
    const prefix = pool.filter((m) => (m.display_name || "").toLowerCase().startsWith(q));
    const rest = pool.filter(
      (m) =>
        !(m.display_name || "").toLowerCase().startsWith(q) &&
        (m.display_name || "").toLowerCase().includes(q),
    );
    return [...prefix, ...rest].slice(0, 6);
  }, [members, mentionQuery, user?.id]);

  // Detect whether the cursor is currently sitting in an @-mention
  // and surface the query slice for the autocomplete dropdown.
  const handleDraftChange = useCallback((value: string) => {
    setDraft(value);
    const el = inputRef.current;
    if (!el) {
      setMentionQuery(null);
      return;
    }
    const caret = el.selectionStart ?? value.length;
    // Walk back from the caret looking for an `@` un-broken by whitespace.
    // If we find a whitespace before an `@`, no mention is active.
    let i = caret - 1;
    while (i >= 0) {
      const ch = value[i];
      if (ch === "@") break;
      if (ch === " " || ch === "\n" || ch === "\t") {
        setMentionQuery(null);
        return;
      }
      i -= 1;
    }
    if (i < 0) {
      setMentionQuery(null);
      return;
    }
    // `@` must be at start of string or preceded by whitespace — otherwise
    // it's part of an email address.
    if (i > 0) {
      const before = value[i - 1];
      if (before !== " " && before !== "\n" && before !== "\t") {
        setMentionQuery(null);
        return;
      }
    }
    const query = value.slice(i + 1, caret);
    setMentionStart(i);
    setMentionQuery(query);
    setMentionIndex(0);
  }, []);

  const insertMention = useCallback(
    (member: Member) => {
      const el = inputRef.current;
      if (!el || mentionQuery === null) return;
      const caret = el.selectionStart ?? draft.length;
      const before = draft.slice(0, mentionStart);
      const after = draft.slice(caret);
      const name = member.display_name || "Persona";
      const next = `${before}@${name} ${after}`;
      setDraft(next);
      setMentionQuery(null);
      // Restore the caret right after the inserted mention.
      requestAnimationFrame(() => {
        const pos = before.length + name.length + 2;
        el.focus();
        el.setSelectionRange(pos, pos);
      });
    },
    [draft, mentionQuery, mentionStart],
  );

  useEffect(() => {
    if (!groupId) return;
    let cancelled = false;
    (async () => {
      try {
        const [g, ms, msgs] = await Promise.all([
          apiGet<{ group: Group; member_count: number }>(`/api/groups/${groupId}`),
          apiGet<{ members: Member[] }>(`/api/groups/${groupId}/members`).catch(() => ({ members: [] as Member[] })),
          apiGet<{ messages: Message[] }>(`/api/groups/${groupId}/messages?limit=100`),
        ]);
        if (cancelled) return;
        setGroup(g.group);
        setMemberCount(g.member_count);
        setMembers(ms.members);
        setMessages(msgs.messages);
        setNotFound(false);
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : "";
        if (msg.toLowerCase().includes("not found")) {
          setNotFound(true);
        } else {
          setError(msg || "Couldn't load group.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [groupId]);

  // Realtime — new inserts on persona_group_messages scoped to this group.
  // The RLS policy (member-only SELECT) prevents non-members from
  // subscribing successfully, so this also defends against a token-only
  // attacker spoofing membership client-side.
  useEffect(() => {
    if (!groupId || notFound) return;
    const sb = getSupabase();
    const channel = sb
      .channel(`group-${groupId}`)
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "persona_group_messages",
          filter: `group_id=eq.${groupId}`,
        },
        (payload) => {
          const msg = payload.new as Message;
          setMessages((prev) => {
            // Already have this real row (from the POST response).
            if (prev.find((m) => m.id === msg.id)) return prev;
            // Match an optimistic message we appended locally on send.
            // Same sender, same content, within a 30s window — that's
            // a strong enough signal without needing a server-issued
            // dedup token.
            const optimistic = prev.find(
              (m) =>
                m.id.startsWith("local-") &&
                m.sender_user_id === msg.sender_user_id &&
                m.content === msg.content &&
                Math.abs(Date.parse(m.created_at) - Date.parse(msg.created_at)) < 30_000,
            );
            if (optimistic) {
              return prev.map((m) => (m.id === optimistic.id ? msg : m));
            }
            return [...prev, msg];
          });
          // An agent-channel arrival clears the pending indicator for
          // that persona's principal. We match on sender_user_id because
          // that's what the dispatch tracks; the orchestrator writes
          // both ids on agent rows.
          if (msg.channel === "agent" && msg.sender_user_id) {
            setPendingReplies((prev) =>
              prev.filter((p) => p.userId !== msg.sender_user_id),
            );
          }
        },
      )
      .subscribe();
    return () => {
      sb.removeChannel(channel);
    };
  }, [groupId, notFound]);

  // Sweep expired pending-reply markers once a second. A persona that
  // never answers (LLM error, no deployed agent on that account, etc.)
  // shouldn't leave a permanent "is replying…" ghost.
  useEffect(() => {
    if (!pendingReplies.length) return;
    const id = window.setInterval(() => {
      const now = Date.now();
      setPendingReplies((prev) => prev.filter((p) => p.expiresAt > now));
    }, 1000);
    return () => window.clearInterval(id);
  }, [pendingReplies.length]);

  // Auto-scroll to bottom whenever the message list grows. Smooth scroll
  // for new content, instant on first paint so users don't see the
  // scroll-zoom animation when they first open the room.
  const firstScrollRef = useRef(true);
  useEffect(() => {
    if (!messages.length) return;
    scrollRef.current?.scrollIntoView({
      behavior: firstScrollRef.current ? "auto" : "smooth",
    });
    firstScrollRef.current = false;
  }, [messages.length]);

  const handleSend = useCallback(async () => {
    if (!groupId || !user) return;
    const content = draft.trim();
    if (!content) return;
    setError(null);

    // Optimistic append — render the message instantly so the chat
    // feels snappy. We tag the id with `local-` so the realtime
    // handler and the POST response both know how to swap it for the
    // real DB row, and so we can roll it back on failure.
    const tempId = `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const displayName =
      (user.user_metadata?.full_name as string | undefined) ||
      (user.user_metadata?.name as string | undefined) ||
      (user.email?.split("@")[0] as string | undefined) ||
      "You";
    const optimistic: Message = {
      id: tempId,
      group_id: groupId,
      sender_user_id: user.id,
      sender_agent_id: myMembership?.agent_id ?? null,
      sender_name: displayName,
      channel: "human",
      content,
      reply_to: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimistic]);
    setDraft("");
    setMentionQuery(null);
    inputRef.current?.focus();
    setSending(true);

    try {
      const r = await apiPost<{
        message: Message | null;
        mentioned_user_ids?: string[];
      }>(`/api/groups/${groupId}/messages`, { content });
      // Swap the optimistic row for the server-confirmed one. If
      // realtime already delivered the real row first (unusual but
      // possible), the realtime handler will have done the swap and
      // this becomes a no-op.
      setMessages((prev) => {
        const real = r.message;
        if (!real) return prev.filter((m) => m.id !== tempId);
        if (prev.some((m) => m.id === real.id)) {
          return prev.filter((m) => m.id !== tempId);
        }
        return prev.map((m) => (m.id === tempId ? real : m));
      });
      const fired = r.mentioned_user_ids || [];
      if (fired.length) {
        const expiresAt = Date.now() + 60_000;
        setPendingReplies((prev) => {
          const next = prev.filter((p) => !fired.includes(p.userId));
          return [...next, ...fired.map((uid) => ({ userId: uid, expiresAt }))];
        });
      }
    } catch (e) {
      // Rollback — drop the optimistic message and restore the draft so
      // the user can fix and retry without retyping.
      setMessages((prev) => prev.filter((m) => m.id !== tempId));
      setDraft(content);
      setError(e instanceof Error ? e.message : "Couldn't send the message.");
    } finally {
      setSending(false);
    }
  }, [groupId, draft, user, myMembership]);

  if (notFound) {
    return (
      <div style={{ maxWidth: 560, margin: "80px auto", padding: "0 24px", textAlign: "center" }}>
        <h1 className="display-m" style={{ marginBottom: 8 }}>Group not found.</h1>
        <p style={{ color: "var(--text-secondary)", margin: "0 0 18px" }}>
          It may have been archived, or you weren&rsquo;t added as a member.
        </p>
        <Link href="/dashboard/groups">
          <Button variant="secondary" leftIcon={<ArrowLeft size={14} strokeWidth={1.8} />}>
            Back to groups
          </Button>
        </Link>
      </div>
    );
  }

  if (loading || !group) {
    return (
      <div style={{ padding: "80px 24px", color: "var(--text-muted)", textAlign: "center" }}>
        Loading…
      </div>
    );
  }

  return (
    <div className="group-chat-shell">
      <header className="group-chat-header">
        <Link href="/dashboard/groups" className="group-back" aria-label="Back to groups">
          <ArrowLeft size={16} strokeWidth={1.8} />
        </Link>
        <span className="group-chat-avatar" aria-hidden>
          {group.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={group.avatar_url} alt="" />
          ) : (
            <span>{(group.name || "?").charAt(0).toUpperCase()}</span>
          )}
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h2 className="group-chat-title">{group.name}</h2>
          <div className="group-chat-meta">
            {group.visibility === "private" ? (
              <Lock size={11} strokeWidth={2} />
            ) : (
              <Globe2 size={11} strokeWidth={2} />
            )}
            <span>{group.visibility === "private" ? "Private" : "Open"}</span>
            <span aria-hidden>·</span>
            <Users size={11} strokeWidth={2} />
            <span>{memberCount} member{memberCount === 1 ? "" : "s"}</span>
          </div>
        </div>
        {isManager && (
          <Link
            href={`/dashboard/groups/${groupId}/settings`}
            className="group-settings-btn"
            aria-label="Group settings"
            title="Settings"
          >
            <SettingsIcon size={16} strokeWidth={1.7} />
          </Link>
        )}
        <HeaderMenu
          group={group}
          groupId={groupId || ""}
          isOwner={isOwner}
          isManager={isManager}
          onArchived={() => router.push("/dashboard/groups")}
        />
      </header>

      <div className="group-chat-body">
        <main className="group-chat-main">
        <div className="group-chat-messages">
          {messages.length === 0 ? (
            <div className="group-chat-empty">
              <p className="group-chat-empty-title">No messages yet.</p>
              <p className="group-chat-empty-sub">
                Say hi. Once your team joins, you&rsquo;ll be able to @mention personas to ask each other questions.
              </p>
            </div>
          ) : (
            <ul className="group-msgs">
              {messages.map((m, i) => {
                const isMine = m.sender_user_id === user?.id;
                const prev = i > 0 ? messages[i - 1] : null;
                // Only show the sender label on the first message of a
                // new run by that sender (or after a 5-min gap). Mirrors
                // the home chat where the avatar+name only appear once
                // at the top of a turn.
                const showSender =
                  !isMine && (
                    !prev ||
                    prev.sender_user_id !== m.sender_user_id ||
                    prev.sender_agent_id !== m.sender_agent_id ||
                    prev.channel !== m.channel ||
                    Date.parse(m.created_at) - Date.parse(prev.created_at) > 5 * 60 * 1000
                  );
                const sender = members.find((mm) => mm.user_id === m.sender_user_id);
                const senderName = m.sender_name || sender?.display_name || (m.channel === "agent" ? "Persona" : "Someone");
                const myAvatar =
                  (user?.user_metadata?.avatar_url as string | undefined) ||
                  (user?.user_metadata?.picture as string | undefined);
                const myName =
                  (user?.user_metadata?.full_name as string | undefined) ||
                  (user?.user_metadata?.name as string | undefined) ||
                  (user?.email?.split("@")[0] as string | undefined) ||
                  "You";
                return (
                  <li
                    key={m.id}
                    className={`group-msg group-msg-${m.channel} ${isMine ? "is-mine" : ""}`}
                  >
                    {!isMine && (
                      <span className="group-msg-avatar" aria-hidden>
                        <Avatar
                          size="sm"
                          name={senderName}
                          src={sender?.avatar_url || undefined}
                          variant="accent"
                        />
                      </span>
                    )}
                    <div className="group-msg-bubble">
                      {showSender && (
                        <div className="group-msg-name">
                          {senderName}
                          {m.channel === "agent" && (
                            <span className="group-msg-tag">via persona</span>
                          )}
                        </div>
                      )}
                      <div className="group-msg-content">
                        {renderWithMentions(m.content, members, user?.id)}
                      </div>
                    </div>
                    {isMine && (
                      <span className="group-msg-avatar" aria-hidden>
                        <Avatar size="sm" name={myName} src={myAvatar} />
                      </span>
                    )}
                  </li>
                );
              })}
              <div ref={scrollRef} />
            </ul>
          )}
        </div>

        <PendingRepliesBar pending={pendingReplies} members={members} />

        <div className="group-composer">
        {!canPost && (
          <div className="group-composer-locked">
            You don&rsquo;t have permission to post in this group.
          </div>
        )}
        {error && <div className="group-composer-error">{error}</div>}
        {mentionQuery !== null && mentionSuggestions.length > 0 && (
          <ul className="mention-picker" role="listbox" aria-label="Mention a member">
            {mentionSuggestions.map((s, idx) => (
              <li
                key={s.user_id}
                role="option"
                aria-selected={idx === mentionIndex}
                className={`mention-picker-row ${idx === mentionIndex ? "is-active" : ""}`}
                onMouseEnter={() => setMentionIndex(idx)}
                onMouseDown={(e) => {
                  e.preventDefault();
                  insertMention(s);
                }}
              >
                <Avatar size="xs" name={s.display_name} src={s.avatar_url || undefined} variant="accent" />
                <span className="mention-picker-name">{s.display_name}</span>
                <span className="mention-picker-role">{s.role}</span>
              </li>
            ))}
          </ul>
        )}
        <div className="group-composer-row">
          <textarea
            ref={inputRef}
            value={draft}
            onChange={(e) => handleDraftChange(e.target.value)}
            onKeyDown={(e) => {
              if (mentionQuery !== null && mentionSuggestions.length > 0) {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setMentionIndex((i) => (i + 1) % mentionSuggestions.length);
                  return;
                }
                if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setMentionIndex(
                    (i) => (i - 1 + mentionSuggestions.length) % mentionSuggestions.length,
                  );
                  return;
                }
                if (e.key === "Enter" || e.key === "Tab") {
                  e.preventDefault();
                  insertMention(mentionSuggestions[mentionIndex]);
                  return;
                }
                if (e.key === "Escape") {
                  e.preventDefault();
                  setMentionQuery(null);
                  return;
                }
              }
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void handleSend();
              }
            }}
            disabled={!canPost || sending}
            rows={1}
            placeholder={
              canPost
                ? "Message your group…  Type @ to mention a member's persona."
                : "Posting is disabled"
            }
            className="group-composer-input"
            maxLength={4000}
          />
          <button
            type="button"
            className="group-composer-send"
            onClick={() => void handleSend()}
            disabled={!canPost || sending || !draft.trim()}
            aria-label="Send message"
          >
            <Send size={16} strokeWidth={1.8} />
          </button>
        </div>
      </div>
        </main>

        <GroupRightRail
          groupId={groupId || ""}
          members={members}
          currentUserId={user?.id}
          isManager={isManager}
          isOwner={myMembership?.role === "owner"}
        />
      </div>
    </div>
  );
}

// Server-side regex equivalent for highlighting. Same shape as
// backend/agent/group_dispatch.py _MENTION_RE so what the user sees as a
// highlighted mention is what the dispatcher will actually fire on.
const MENTION_RE = /@([A-Z][A-Za-z0-9_]{0,30}(?:\s+[A-Z][A-Za-z0-9_]{0,30})?)/g;

function renderWithMentions(
  content: string,
  members: Member[],
  myUserId: string | undefined,
): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const lower = (s: string | null | undefined) => (s || "").toLowerCase();
  let cursor = 0;
  let key = 0;
  for (const match of content.matchAll(MENTION_RE)) {
    const idx = match.index ?? 0;
    if (idx > cursor) {
      nodes.push(<span key={key++}>{content.slice(cursor, idx)}</span>);
    }
    const raw = match[1];
    // Lookup the resolved member so we can flag "@you" vs others differently.
    const target = members.find((m) => lower(m.display_name) === raw.toLowerCase());
    const isMe = !!target && target.user_id === myUserId;
    nodes.push(
      <span
        key={key++}
        className={`group-mention ${isMe ? "is-me" : ""} ${target ? "" : "is-unresolved"}`}
      >
        @{raw}
      </span>,
    );
    cursor = idx + match[0].length;
  }
  if (cursor < content.length) {
    nodes.push(<span key={key++}>{content.slice(cursor)}</span>);
  }
  return nodes.length ? nodes : [<span key={0}>{content}</span>];
}

// Header kebab menu — Settings, Copy invite link, Archive (owner only).
// Surfaces destructive actions where users actually look for them
// instead of two clicks deep in the settings page Danger zone.
function HeaderMenu({
  group,
  groupId,
  isOwner,
  isManager,
  onArchived,
}: {
  group: Group;
  groupId: string;
  isOwner: boolean;
  isManager: boolean;
  onArchived: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const inviteUrl =
    group.invite_token && typeof window !== "undefined"
      ? `${window.location.origin}/g/${group.slug}/${group.invite_token}`
      : null;

  const handleCopyInvite = useCallback(async () => {
    if (!inviteUrl) return;
    try {
      await navigator.clipboard.writeText(inviteUrl);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard blocked; menu shows the unsuccessful state silently */
    }
  }, [inviteUrl]);

  const handleArchive = useCallback(async () => {
    if (!groupId) return;
    if (
      !window.confirm(
        `Archive “${group.name}”? Members can no longer see it. Messages are kept but no one can post. There's no undo from the UI.`,
      )
    ) {
      return;
    }
    setArchiving(true);
    try {
      await apiDelete(`/api/groups/${groupId}`);
      invalidate("/api/groups/");
      onArchived();
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "Couldn't archive the group.");
    } finally {
      setArchiving(false);
    }
  }, [groupId, group.name, onArchived]);

  return (
    <div className="group-header-menu-wrap" ref={wrapRef}>
      <button
        type="button"
        className="group-settings-btn"
        aria-label="More group actions"
        aria-haspopup="menu"
        aria-expanded={open}
        title="More actions"
        onClick={() => setOpen((o) => !o)}
      >
        <MoreHorizontal size={16} strokeWidth={1.7} />
      </button>
      {open && (
        <ul className="group-header-menu" role="menu">
          {isManager && (
            <li role="none">
              <Link
                href={`/dashboard/groups/${groupId}/settings`}
                className="group-header-menu-item"
                role="menuitem"
                onClick={() => setOpen(false)}
              >
                <SettingsIcon size={14} strokeWidth={1.7} />
                Group settings
              </Link>
            </li>
          )}
          {inviteUrl && (
            <li role="none">
              <button
                type="button"
                className="group-header-menu-item"
                role="menuitem"
                onClick={() => void handleCopyInvite()}
              >
                {copied ? (
                  <Check size={14} strokeWidth={1.9} />
                ) : (
                  <Copy size={14} strokeWidth={1.7} />
                )}
                {copied ? "Link copied" : "Copy invite link"}
              </button>
            </li>
          )}
          {isOwner && (
            <>
              <li className="group-header-menu-divider" role="separator" />
              <li role="none">
                <button
                  type="button"
                  className="group-header-menu-item is-danger"
                  role="menuitem"
                  onClick={() => void handleArchive()}
                  disabled={archiving}
                >
                  <Trash2 size={14} strokeWidth={1.7} />
                  {archiving ? "Archiving…" : "Archive group"}
                </button>
              </li>
            </>
          )}
        </ul>
      )}
    </div>
  );
}

// Lazy-import-style brief loader. We only fetch when the user opens
// the Brief tab so the chat view's first paint stays light. After init,
// re-fetches are cheap (Google Docs READ; ~200ms) and we don't auto-poll
// — the editor is what triggers a refresh.
interface GroupBriefData {
  exists: boolean;
  doc_id?: string;
  url?: string;
  content?: string;
  description?: string;
  error?: string;
}

function GroupRightRail({
  groupId,
  members,
  currentUserId,
  isManager,
  isOwner,
}: {
  groupId: string;
  members: Member[];
  currentUserId: string | undefined;
  isManager: boolean;
  isOwner: boolean;
}) {
  const [tab, setTab] = useState<"people" | "brief" | "schedule" | "memory">("people");
  const [brief, setBrief] = useState<GroupBriefData | null>(null);
  const [briefLoading, setBriefLoading] = useState(false);
  const [briefError, setBriefError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [editDraft, setEditDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [initing, setIniting] = useState(false);

  // Fetch on first tab-switch to Brief. The fetched payload is cached in
  // local state for the lifetime of the page; users who want a refresh
  // hit the explicit "Reload" button.
  useEffect(() => {
    if (tab !== "brief" || !groupId || brief !== null) return;
    let cancelled = false;
    (async () => {
      setBriefLoading(true);
      setBriefError(null);
      try {
        const data = await apiGet<GroupBriefData>(`/api/groups/${groupId}/brief`);
        if (!cancelled) setBrief(data);
      } catch (e) {
        if (!cancelled) setBriefError(e instanceof Error ? e.message : "Couldn't load brief.");
      } finally {
        if (!cancelled) setBriefLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [tab, groupId, brief]);

  const reloadBrief = useCallback(async () => {
    setBrief(null);
    setBriefError(null);
    setBriefLoading(true);
    try {
      const data = await apiGet<GroupBriefData>(`/api/groups/${groupId}/brief`);
      setBrief(data);
    } catch (e) {
      setBriefError(e instanceof Error ? e.message : "Couldn't load brief.");
    } finally {
      setBriefLoading(false);
    }
  }, [groupId]);

  const handleInit = useCallback(async () => {
    setIniting(true);
    setBriefError(null);
    try {
      await apiPost(`/api/groups/${groupId}/brief/init`, {});
      invalidate(`/api/groups/${groupId}/brief`);
      await reloadBrief();
    } catch (e) {
      setBriefError(e instanceof Error ? e.message : "Couldn't initialize brief.");
    } finally {
      setIniting(false);
    }
  }, [groupId, reloadBrief]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setBriefError(null);
    try {
      await apiPatch(`/api/groups/${groupId}/brief`, { content: editDraft });
      invalidate(`/api/groups/${groupId}/brief`);
      setEditing(false);
      await reloadBrief();
    } catch (e) {
      setBriefError(e instanceof Error ? e.message : "Couldn't save brief.");
    } finally {
      setSaving(false);
    }
  }, [editDraft, groupId, reloadBrief]);

  return (
    <aside className="group-chat-roster">
      <div className="group-rail-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "people"}
          className={`group-rail-tab ${tab === "people" ? "is-active" : ""}`}
          onClick={() => setTab("people")}
        >
          People
          <span className="group-rail-tab-count">{members.length}</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "brief"}
          className={`group-rail-tab ${tab === "brief" ? "is-active" : ""}`}
          onClick={() => setTab("brief")}
        >
          Brief
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "schedule"}
          className={`group-rail-tab ${tab === "schedule" ? "is-active" : ""}`}
          onClick={() => setTab("schedule")}
        >
          Schedule
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "memory"}
          className={`group-rail-tab ${tab === "memory" ? "is-active" : ""}`}
          onClick={() => setTab("memory")}
        >
          Memory
        </button>
      </div>

      {tab === "people" ? (
        <>
          <ul className="group-roster-list">
            {members.map((m) => (
              <li key={m.user_id} className="group-roster-row">
                <Avatar
                  size="sm"
                  name={m.display_name}
                  src={m.avatar_url || undefined}
                  variant="accent"
                />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="group-roster-name">
                    {m.display_name}
                    {m.user_id === currentUserId && (
                      <span className="group-roster-you">you</span>
                    )}
                  </div>
                  <div className="group-roster-role">{m.role}</div>
                </div>
              </li>
            ))}
          </ul>
          {isManager && (
            <Link
              href={`/dashboard/groups/${groupId}/settings`}
              className="btn btn-secondary btn-sm group-rail-cta"
            >
              Invite or manage →
            </Link>
          )}
        </>
      ) : tab === "schedule" ? (
        <GroupSchedulePane groupId={groupId} />
      ) : tab === "memory" ? (
        <GroupMemoryPane groupId={groupId} canEdit={isManager} />
      ) : (
        <div className="group-brief-pane">
          {briefError && (
            <div className="group-composer-error" style={{ marginBottom: 8 }}>
              {briefError}
            </div>
          )}
          {briefLoading && !brief ? (
            <p style={{ color: "var(--text-muted)", fontSize: 13 }}>Loading…</p>
          ) : !brief ? null : !brief.exists ? (
            <div className="group-brief-empty">
              <p>
                No shared brief yet. The owner can start one — a Google Doc
                visible only to members, used as the team&rsquo;s collective
                context.
              </p>
              {isOwner ? (
                <Button onClick={() => void handleInit()} disabled={initing} size="sm">
                  {initing ? "Creating…" : "Start the group brief"}
                </Button>
              ) : (
                <p style={{ color: "var(--text-muted)", fontSize: 12 }}>
                  Ask the group owner to create one.
                </p>
              )}
            </div>
          ) : editing ? (
            <>
              <textarea
                className="input group-brief-textarea"
                value={editDraft}
                onChange={(e) => setEditDraft(e.target.value)}
                rows={14}
                maxLength={50000}
                autoFocus
              />
              <div className="group-brief-actions">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setEditing(false)}
                  disabled={saving}
                >
                  Cancel
                </Button>
                <Button onClick={() => void handleSave()} disabled={saving} size="sm">
                  {saving ? "Saving…" : "Save"}
                </Button>
              </div>
            </>
          ) : (
            <>
              <div className="group-brief-body">
                {brief.content?.trim() || (
                  <span className="group-brief-empty-hint">
                    Brief doc exists but it&rsquo;s empty. {isManager && "Edit it to add team context."}
                  </span>
                )}
              </div>
              <div className="group-brief-actions">
                {brief.url && (
                  <a
                    href={brief.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="btn btn-secondary btn-sm"
                  >
                    Open in Docs ↗
                  </a>
                )}
                {isManager && (
                  <Button
                    size="sm"
                    onClick={() => {
                      setEditDraft(brief.content || "");
                      setEditing(true);
                    }}
                  >
                    Edit
                  </Button>
                )}
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => void reloadBrief()}
                  title="Re-read from Google Docs"
                >
                  Reload
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </aside>
  );
}

interface AvailMember {
  user_id: string;
  display_name: string;
  has_calendar: boolean;
  busy: Array<{ start: string; end: string }>;
  error: string | null;
}

interface CommonSlot {
  start: string;
  end: string;
  participants: string[];
}

interface AvailabilityResponse {
  window: { start: string; end: string };
  members: AvailMember[];
  common_slots: CommonSlot[];
  duration_minutes: number;
}

const DURATION_OPTIONS: Array<{ label: string; value: number }> = [
  { label: "30 min", value: 30 },
  { label: "45 min", value: 45 },
  { label: "1 hour", value: 60 },
];
const RANGE_OPTIONS: Array<{ label: string; days: number }> = [
  { label: "Next 3 days", days: 3 },
  { label: "Next 7 days", days: 7 },
  { label: "Next 14 days", days: 14 },
];

function GroupSchedulePane({ groupId }: { groupId: string }) {
  const [days, setDays] = useState(7);
  const [duration, setDuration] = useState(30);
  const [data, setData] = useState<AvailabilityResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [proposingSlot, setProposingSlot] = useState<CommonSlot | null>(null);

  const tzOffsetMinutes = useMemo(() => {
    // getTimezoneOffset returns minutes WEST of UTC (positive for west).
    // We pass the inverse so the backend's local-time projection adds the
    // right number of minutes to a UTC cursor.
    if (typeof window === "undefined") return 0;
    return -new Date().getTimezoneOffset();
  }, []);

  const fetchAvailability = useCallback(async () => {
    if (!groupId) return;
    setLoading(true);
    setError(null);
    try {
      const start = new Date();
      // Start tomorrow morning local — looking at today's availability is
      // rarely useful and clutters the slot list with already-past times.
      start.setHours(0, 0, 0, 0);
      start.setDate(start.getDate() + 1);
      const end = new Date(start);
      end.setDate(end.getDate() + days);
      const qs = new URLSearchParams({
        start: start.toISOString(),
        end: end.toISOString(),
        duration_minutes: String(duration),
        tz_offset_minutes: String(tzOffsetMinutes),
      });
      const r = await apiGet<AvailabilityResponse>(
        `/api/groups/${groupId}/availability?${qs.toString()}`,
      );
      setData(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load availability.");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [groupId, days, duration, tzOffsetMinutes]);

  const noCalMembers = useMemo(() => {
    return (data?.members || []).filter((m) => !m.has_calendar);
  }, [data]);

  return (
    <div className="group-schedule-pane">
      <div className="group-schedule-controls">
        <select
          className="input group-schedule-select"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          aria-label="Date range"
        >
          {RANGE_OPTIONS.map((r) => (
            <option key={r.days} value={r.days}>
              {r.label}
            </option>
          ))}
        </select>
        <select
          className="input group-schedule-select"
          value={duration}
          onChange={(e) => setDuration(Number(e.target.value))}
          aria-label="Meeting duration"
        >
          {DURATION_OPTIONS.map((d) => (
            <option key={d.value} value={d.value}>
              {d.label}
            </option>
          ))}
        </select>
        <Button size="sm" onClick={() => void fetchAvailability()} disabled={loading}>
          {loading ? "Looking…" : data ? "Refresh" : "Find slots"}
        </Button>
      </div>

      {error && (
        <div className="group-composer-error" style={{ marginTop: 10 }}>
          {error}
        </div>
      )}

      {data && (
        <>
          {noCalMembers.length > 0 && (
            <div className="group-schedule-note">
              No calendar data for{" "}
              {noCalMembers.map((m) => m.display_name).join(", ")}
              {" "}— they&rsquo;re excluded from the common-slot intersection.
            </div>
          )}
          {data.common_slots.length === 0 ? (
            <p className="group-schedule-empty">
              No slot in the next {days} day{days === 1 ? "" : "s"} works for
              everyone with a connected calendar. Try a longer range or a
              shorter duration.
            </p>
          ) : (
            <ul className="group-schedule-list">
              {data.common_slots.map((s) => (
                <li key={s.start} className="group-schedule-slot">
                  <div>
                    <div className="group-schedule-slot-when">
                      {formatSlotWhen(s.start, s.end)}
                    </div>
                    <div className="group-schedule-slot-participants">
                      {s.participants.length} member{s.participants.length === 1 ? "" : "s"} free
                    </div>
                  </div>
                  <Button
                    size="sm"
                    onClick={() => setProposingSlot(s)}
                  >
                    Propose →
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {!data && !loading && (
        <p className="group-schedule-hint">
          Click <strong>Find slots</strong> to see times that work for every
          member with a connected calendar. Members without calendars are
          excluded — they&rsquo;ll need to RSVP manually after the proposal.
        </p>
      )}

      {proposingSlot && (
        <ProposeMeetingModal
          groupId={groupId}
          slot={proposingSlot}
          onClose={() => setProposingSlot(null)}
          onProposed={() => {
            setProposingSlot(null);
            // Refresh availability so the slot doesn't reappear.
            void fetchAvailability();
          }}
        />
      )}
    </div>
  );
}

function formatSlotWhen(start: string, end: string): string {
  const s = new Date(start);
  const e = new Date(end);
  const sameDay =
    s.getFullYear() === e.getFullYear() &&
    s.getMonth() === e.getMonth() &&
    s.getDate() === e.getDate();
  const day = s.toLocaleDateString([], {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
  const sTime = s.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const eTime = e.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (sameDay) return `${day} · ${sTime} – ${eTime}`;
  const dayEnd = e.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
  return `${day} ${sTime} → ${dayEnd} ${eTime}`;
}

function ProposeMeetingModal({
  groupId,
  slot,
  onClose,
  onProposed,
}: {
  groupId: string;
  slot: CommonSlot;
  onClose: () => void;
  onProposed: () => void;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [location, setLocation] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tz = useMemo(
    () =>
      typeof Intl !== "undefined"
        ? Intl.DateTimeFormat().resolvedOptions().timeZone
        : undefined,
    [],
  );

  const handleSubmit = useCallback(async () => {
    if (!title.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      await apiPost(`/api/groups/${groupId}/meetings`, {
        title: title.trim(),
        start: slot.start,
        end: slot.end,
        description: description.trim() || undefined,
        location: location.trim() || undefined,
        time_zone: tz,
      });
      // Drop the cached availability and messages so the chat sees the
      // new system-channel proposal and the Schedule pane removes the
      // now-booked slot from the common-slots list.
      invalidate(`/api/groups/${groupId}/availability`);
      invalidate(`/api/groups/${groupId}/messages`);
      onProposed();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't propose the meeting.");
    } finally {
      setSubmitting(false);
    }
  }, [title, description, location, tz, slot, groupId, onProposed]);

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal-shell"
        role="dialog"
        aria-modal="true"
        aria-labelledby="propose-meeting-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="propose-meeting-title" className="modal-title">Propose a meeting</h2>
        <p className="modal-sub">
          {formatSlotWhen(slot.start, slot.end)} · invites go to{" "}
          {slot.participants.length} member{slot.participants.length === 1 ? "" : "s"}.
        </p>

        <label className="modal-label" htmlFor="pm-title">Title</label>
        <input
          id="pm-title"
          autoFocus
          className="input"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Sprint demo, kickoff, founder sync"
          maxLength={200}
        />

        <label className="modal-label" htmlFor="pm-desc" style={{ marginTop: 12 }}>
          Description <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>· optional</span>
        </label>
        <textarea
          id="pm-desc"
          className="input"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={2}
          maxLength={2000}
          style={{ resize: "vertical" }}
        />

        <label className="modal-label" htmlFor="pm-loc" style={{ marginTop: 12 }}>
          Location / link <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>· optional</span>
        </label>
        <input
          id="pm-loc"
          className="input"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          placeholder="Zoom link, room, etc."
          maxLength={200}
        />

        {error && <div className="group-composer-error" style={{ marginTop: 12 }}>{error}</div>}

        <div className="modal-actions">
          <Button variant="secondary" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={() => void handleSubmit()} disabled={!title.trim() || submitting}>
            {submitting ? "Proposing…" : "Send invites"}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ── Group Memory (phase 4) ────────────────────────────────────────
// Group constraints — short guardrails every member's persona must
// respect when answering in this room. Read by all members; managed by
// owner/admin.
interface GroupConstraint {
  id: string;
  kind: "fact" | "rule" | "voice";
  text: string;
  created_by_user_id: string | null;
  created_at: string;
}

const KIND_LABEL: Record<GroupConstraint["kind"], string> = {
  fact: "Fact",
  rule: "Rule",
  voice: "Voice",
};

const KIND_HELP: Record<GroupConstraint["kind"], string> = {
  fact: "Something the team has agreed on — e.g. 'Our launch is May 20'.",
  rule: "Something to avoid — e.g. 'Don't quote pricing externally'.",
  voice: "Style or tone guidance — e.g. 'Warm but precise, no exclamation marks'.",
};

function GroupMemoryPane({
  groupId,
  canEdit,
}: {
  groupId: string;
  canEdit: boolean;
}) {
  const [items, setItems] = useState<GroupConstraint[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draftKind, setDraftKind] = useState<GroupConstraint["kind"]>("rule");
  const [draftText, setDraftText] = useState("");
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    if (!groupId) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await apiGet<{ constraints: GroupConstraint[] }>(
          `/api/groups/${groupId}/constraints`,
        );
        if (cancelled) return;
        setItems(r.constraints);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Couldn't load group memory.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [groupId]);

  const handleAdd = useCallback(async () => {
    const text = draftText.trim();
    if (!text) return;
    setAdding(true);
    setError(null);
    try {
      const r = await apiPost<{ constraint: GroupConstraint }>(
        `/api/groups/${groupId}/constraints`,
        { kind: draftKind, text },
      );
      if (r.constraint) setItems((prev) => [...(prev || []), r.constraint]);
      invalidate(`/api/groups/${groupId}/constraints`);
      setDraftText("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't add the rule.");
    } finally {
      setAdding(false);
    }
  }, [groupId, draftKind, draftText]);

  const handleRemove = useCallback(
    async (id: string) => {
      const prev = items;
      setItems((cur) => (cur ? cur.filter((c) => c.id !== id) : cur));
      try {
        await apiDelete(`/api/groups/${groupId}/constraints/${id}`);
        invalidate(`/api/groups/${groupId}/constraints`);
      } catch (e) {
        setItems(prev);
        setError(e instanceof Error ? e.message : "Couldn't remove the rule.");
      }
    },
    [groupId, items],
  );

  return (
    <div className="group-memory-pane">
      <p className="group-memory-intro">
        Short guardrails every member&rsquo;s persona must follow when replying in
        this room. Think 1-line constraints — not docs.
      </p>

      {error && (
        <div className="group-composer-error" style={{ margin: "8px 0" }}>{error}</div>
      )}

      {loading ? (
        <p style={{ color: "var(--text-muted)", fontSize: 13 }}>Loading…</p>
      ) : !items || items.length === 0 ? (
        <p className="group-memory-empty">
          No rules yet. {canEdit ? "Add one below — start with a single sharp constraint." : "Ask the owner to set the team's ground rules."}
        </p>
      ) : (
        <ul className="group-memory-list">
          {(["rule", "fact", "voice"] as const).map((k) => {
            const inKind = items.filter((c) => c.kind === k);
            if (inKind.length === 0) return null;
            return (
              <li key={k} className="group-memory-section">
                <h4 className={`group-memory-kind kind-${k}`}>{KIND_LABEL[k]}s</h4>
                <ul className="group-memory-sublist">
                  {inKind.map((c) => (
                    <li key={c.id} className="group-memory-row">
                      <span className="group-memory-text">{c.text}</span>
                      {canEdit && (
                        <button
                          type="button"
                          className="group-memory-remove"
                          onClick={() => void handleRemove(c.id)}
                          aria-label="Remove this rule"
                          title="Remove"
                        >
                          ×
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              </li>
            );
          })}
        </ul>
      )}

      {canEdit && (
        <div className="group-memory-add">
          <label className="modal-label" htmlFor="gm-kind">Kind</label>
          <select
            id="gm-kind"
            className="input group-schedule-select"
            value={draftKind}
            onChange={(e) => setDraftKind(e.target.value as GroupConstraint["kind"])}
          >
            {(["rule", "fact", "voice"] as const).map((k) => (
              <option key={k} value={k}>
                {KIND_LABEL[k]}
              </option>
            ))}
          </select>
          <p className="group-memory-help">{KIND_HELP[draftKind]}</p>
          <textarea
            className="input"
            value={draftText}
            onChange={(e) => setDraftText(e.target.value)}
            placeholder="One sentence — the sharper, the better."
            rows={2}
            maxLength={400}
            style={{ resize: "vertical", marginTop: 6 }}
          />
          <Button
            size="sm"
            onClick={() => void handleAdd()}
            disabled={adding || !draftText.trim()}
            style={{ marginTop: 8 }}
          >
            {adding ? "Adding…" : "Add rule"}
          </Button>
        </div>
      )}
    </div>
  );
}

function PendingRepliesBar({
  pending,
  members,
}: {
  pending: Array<{ userId: string; expiresAt: number }>;
  members: Member[];
}) {
  if (!pending.length) return null;
  return (
    <div className="group-pending" role="status" aria-live="polite">
      {pending.map((p) => {
        const m = members.find((mm) => mm.user_id === p.userId);
        const name = m?.display_name || "A persona";
        return (
          <span key={p.userId} className="group-pending-chip">
            <span className="group-pending-dot" aria-hidden />
            {name}&rsquo;s persona is thinking…
          </span>
        );
      })}
    </div>
  );
}
