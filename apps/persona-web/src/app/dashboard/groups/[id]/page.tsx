"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Settings as SettingsIcon, Send, Users, Lock, Globe2 } from "lucide-react";
import { Avatar, Button } from "@/components/ui";
import { useDashboard } from "@/contexts/DashboardContext";
import { apiGet, apiPost } from "@/lib/api";
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
          setMessages((prev) =>
            prev.find((m) => m.id === msg.id) ? prev : [...prev, msg],
          );
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
    if (!groupId) return;
    const content = draft.trim();
    if (!content) return;
    setSending(true);
    setError(null);
    try {
      const r = await apiPost<{ mentioned_user_ids?: string[] }>(
        `/api/groups/${groupId}/messages`,
        { content },
      );
      setDraft("");
      setMentionQuery(null);
      inputRef.current?.focus();
      const fired = r.mentioned_user_ids || [];
      if (fired.length) {
        const expiresAt = Date.now() + 60_000;
        setPendingReplies((prev) => {
          const next = prev.filter((p) => !fired.includes(p.userId));
          return [...next, ...fired.map((uid) => ({ userId: uid, expiresAt }))];
        });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't send the message.");
    } finally {
      setSending(false);
    }
  }, [groupId, draft]);

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
          <Link href={`/dashboard/groups/${groupId}/settings`} className="group-settings-btn" aria-label="Group settings">
            <SettingsIcon size={16} strokeWidth={1.7} />
          </Link>
        )}
      </header>

      <div className="group-chat-body">
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
                const showHeader =
                  !prev ||
                  prev.sender_user_id !== m.sender_user_id ||
                  prev.sender_agent_id !== m.sender_agent_id ||
                  prev.channel !== m.channel ||
                  Date.parse(m.created_at) - Date.parse(prev.created_at) > 5 * 60 * 1000;
                const sender = members.find((mm) => mm.user_id === m.sender_user_id);
                const senderName = m.sender_name || sender?.display_name || (m.channel === "agent" ? "Persona" : "Someone");
                return (
                  <li
                    key={m.id}
                    className={`group-msg group-msg-${m.channel} ${isMine ? "is-mine" : ""}`}
                  >
                    {showHeader && (
                      <div className="group-msg-head">
                        <Avatar
                          size="xs"
                          name={senderName}
                          src={sender?.avatar_url || undefined}
                          variant="accent"
                        />
                        <span className="group-msg-sender">{senderName}</span>
                        {m.channel === "agent" && (
                          <span className="group-msg-tag">via persona</span>
                        )}
                        <span className="group-msg-time">{formatTime(m.created_at)}</span>
                      </div>
                    )}
                    <div className={`msg-bubble-${isMine ? "user" : "ai"} group-msg-bubble`}>
                      {renderWithMentions(m.content, members, user?.id)}
                    </div>
                  </li>
                );
              })}
              <div ref={scrollRef} />
            </ul>
          )}
        </div>

        <aside className="group-chat-roster">
          <h3 className="group-roster-title">Members</h3>
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
                    {m.user_id === user?.id && <span className="group-roster-you">you</span>}
                  </div>
                  <div className="group-roster-role">{m.role}</div>
                </div>
              </li>
            ))}
          </ul>
          {isManager && (
            <Link
              href={`/dashboard/groups/${groupId}/settings`}
              className="btn btn-secondary btn-sm"
              style={{ marginTop: 12, textAlign: "center", display: "block", textDecoration: "none" }}
            >
              Invite or manage →
            </Link>
          )}
        </aside>
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
    </div>
  );
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const sameDay =
      d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() &&
      d.getDate() === now.getDate();
    const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    if (sameDay) return time;
    return `${d.toLocaleDateString([], { month: "short", day: "numeric" })} · ${time}`;
  } catch {
    return "";
  }
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
