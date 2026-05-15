"use client";

import { useCallback, useEffect, useState } from "react";
import { Search, UserPlus, X as XIcon } from "lucide-react";
import { Avatar, Button } from "@/components/ui";
import {
  createGroupInvitation,
  listGroupInvitations,
  revokeGroupInvitation,
  searchInvitableUsers,
  type GroupInvitation,
  type InvitableUser,
} from "@/lib/group-invitations";

export interface InvitePeoplePanelProps {
  groupId: string;
  canInvite: boolean;
  showHint?: boolean;
  compact?: boolean;
}

export function InvitePeoplePanel({
  groupId,
  canInvite,
  showHint = true,
  compact = false,
}: InvitePeoplePanelProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<InvitableUser[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [pending, setPending] = useState<GroupInvitation[]>([]);
  const [pendingError, setPendingError] = useState<string | null>(null);
  const [pendingLoading, setPendingLoading] = useState(false);
  const [working, setWorking] = useState<string | null>(null);
  const [info, setInfo] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const refreshPending = useCallback(async () => {
    if (!groupId || !canInvite) return;
    setPendingLoading(true);
    try {
      const res = await listGroupInvitations(groupId);
      setPending(res.invitations || []);
      setPendingError(null);
    } catch (e) {
      setPendingError(
        e instanceof Error ? e.message : "Couldn't load pending invitations.",
      );
    } finally {
      setPendingLoading(false);
    }
  }, [canInvite, groupId]);

  useEffect(() => {
    void refreshPending();
  }, [refreshPending]);

  useEffect(() => {
    if (!groupId || !canInvite) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setSearching(true);
      try {
        const res = await searchInvitableUsers(groupId, query.trim(), {
          limit: compact ? 8 : 12,
          signal: controller.signal,
        });
        if (!controller.signal.aborted) {
          setResults(res.results || []);
          setSearchError(null);
        }
      } catch (e) {
        if (controller.signal.aborted) return;
        setSearchError(e instanceof Error ? e.message : "Search failed.");
      } finally {
        if (!controller.signal.aborted) setSearching(false);
      }
    }, 220);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [canInvite, compact, groupId, query]);

  const handleInvite = useCallback(
    async (target: InvitableUser) => {
      setWorking(target.user_id);
      setInfo(null);
      try {
        await createGroupInvitation(groupId, { user_id: target.user_id });
        setResults((cur) => cur.filter((r) => r.user_id !== target.user_id));
        setInfo({
          kind: "ok",
          text: `Invited ${target.name}. They'll see it in their inbox.`,
        });
        await refreshPending();
      } catch (e) {
        setInfo({
          kind: "err",
          text: e instanceof Error ? e.message : "Couldn't send invite.",
        });
      } finally {
        setWorking(null);
      }
    },
    [groupId, refreshPending],
  );

  const handleRevoke = useCallback(
    async (invite: GroupInvitation) => {
      setWorking(invite.id);
      setInfo(null);
      try {
        await revokeGroupInvitation(groupId, invite.id);
        setPending((cur) => cur.filter((r) => r.id !== invite.id));
      } catch (e) {
        setInfo({
          kind: "err",
          text: e instanceof Error ? e.message : "Couldn't revoke invite.",
        });
      } finally {
        setWorking(null);
      }
    },
    [groupId],
  );

  if (!canInvite) return null;

  return (
    <div className={`invite-panel ${compact ? "is-compact" : ""}`}>
      {showHint && !compact && (
        <p
          style={{
            color: "var(--text-secondary)",
            fontSize: 13,
            margin: "0 0 14px",
          }}
        >
          Search the persona registry by name. The person you invite gets a card
          in their inbox and joins only if they accept.
        </p>
      )}

      <div className="invite-search-wrap">
        <Search
          size={14}
          strokeWidth={1.9}
          className="invite-search-icon"
          aria-hidden
        />
        <input
          type="text"
          className="invite-search-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by name…"
          aria-label="Search people to invite"
          autoComplete="off"
        />
        {query && (
          <button
            type="button"
            className="invite-search-clear"
            onClick={() => setQuery("")}
            aria-label="Clear search"
          >
            <XIcon size={13} strokeWidth={2} />
          </button>
        )}
      </div>

      {info && (
        <div className={`invite-banner tone-${info.kind}`} role="status">
          {info.text}
        </div>
      )}

      <ul className="invite-result-list">
        {results.length === 0 && !searching && (
          <li className="invite-empty">
            {query.trim()
              ? `No matches for "${query.trim()}".`
              : "Start typing a name."}
          </li>
        )}
        {results.map((r) => (
          <li key={r.user_id} className="invite-result-row">
            <Avatar
              size="sm"
              name={r.name}
              src={r.avatar_url || undefined}
              variant="accent"
            />
            <div className="invite-result-text">
              <strong>{r.name}</strong>
              {r.description && !compact && <small>{r.description}</small>}
            </div>
            <Button
              size="sm"
              onClick={() => void handleInvite(r)}
              disabled={working === r.user_id}
              leftIcon={<UserPlus size={13} strokeWidth={1.9} />}
            >
              {working === r.user_id ? "…" : "Invite"}
            </Button>
          </li>
        ))}
      </ul>
      {searchError && <div className="invite-banner tone-err">{searchError}</div>}

      {pending.length > 0 && (
        <>
          <div className="invite-pending-head">
            Pending invitations · {pending.length}
          </div>
          <ul className="invite-result-list">
            {pending.map((p) => (
              <li key={p.id} className="invite-result-row">
                <Avatar
                  size="sm"
                  name={p.invitee_name || "Persona"}
                  src={p.invitee_avatar_url || undefined}
                  variant="accent"
                />
                <div className="invite-result-text">
                  <strong>{p.invitee_name || "Persona"}</strong>
                  <small>Sent {relativeShortTime(p.created_at)}</small>
                </div>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => void handleRevoke(p)}
                  disabled={working === p.id}
                  leftIcon={<XIcon size={13} strokeWidth={1.9} />}
                >
                  {working === p.id ? "…" : "Revoke"}
                </Button>
              </li>
            ))}
          </ul>
        </>
      )}
      {pendingError && !pendingLoading && (
        <div className="invite-banner tone-err">{pendingError}</div>
      )}
    </div>
  );
}

function relativeShortTime(iso: string): string {
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "";
  const delta = Math.max(0, Date.now() - t);
  const m = Math.floor(delta / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}
