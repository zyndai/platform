"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  Copy,
  Check,
  RefreshCw,
  Trash2,
  Shield,
  User as UserIcon,
  ChevronDown,
  Crown,
} from "lucide-react";
import { Avatar, Button } from "@/components/ui";
import { useDashboard } from "@/contexts/DashboardContext";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";

interface Group {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  avatar_url: string | null;
  visibility: "private" | "open";
  owner_user_id: string;
  invite_token: string | null;
  archived_at: string | null;
  join_domain: string | null;
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

export default function GroupSettingsPage() {
  const params = useParams<{ id: string }>();
  const groupId = params?.id;
  const { user } = useDashboard();
  const router = useRouter();

  const [group, setGroup] = useState<Group | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<"private" | "open">("private");
  const [joinDomain, setJoinDomain] = useState("");
  const [savingDetails, setSavingDetails] = useState(false);
  const [savedTick, setSavedTick] = useState(0);

  const [inviteCopied, setInviteCopied] = useState(false);
  const [rotating, setRotating] = useState(false);

  const myMembership = useMemo(
    () => members.find((m) => m.user_id === user?.id) ?? null,
    [members, user?.id],
  );
  const isOwner = myMembership?.role === "owner";
  const canManage = isOwner || myMembership?.role === "admin";

  const fetchAll = useCallback(async () => {
    if (!groupId) return;
    try {
      const [g, ms] = await Promise.all([
        apiGet<{ group: Group; member_count: number }>(`/api/groups/${groupId}`),
        apiGet<{ members: Member[] }>(`/api/groups/${groupId}/members`),
      ]);
      setGroup(g.group);
      setName(g.group.name);
      setDescription(g.group.description || "");
      setVisibility(g.group.visibility);
      setJoinDomain(g.group.join_domain || "");
      setMembers(ms.members);
      setNotFound(false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "";
      if (msg.toLowerCase().includes("not found")) {
        setNotFound(true);
      } else {
        setError(msg || "Couldn't load settings.");
      }
    } finally {
      setLoading(false);
    }
  }, [groupId]);

  useEffect(() => {
    if (!groupId) return;
    let cancelled = false;
    (async () => {
      try {
        const [g, ms] = await Promise.all([
          apiGet<{ group: Group; member_count: number }>(`/api/groups/${groupId}`),
          apiGet<{ members: Member[] }>(`/api/groups/${groupId}/members`),
        ]);
        if (cancelled) return;
        setGroup(g.group);
        setName(g.group.name);
        setDescription(g.group.description || "");
        setVisibility(g.group.visibility);
        setJoinDomain(g.group.join_domain || "");
        setMembers(ms.members);
        setNotFound(false);
      } catch (e) {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : "";
        if (msg.toLowerCase().includes("not found")) {
          setNotFound(true);
        } else {
          setError(msg || "Couldn't load settings.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [groupId]);

  const handleSaveDetails = useCallback(async () => {
    if (!groupId) return;
    setSavingDetails(true);
    setError(null);
    try {
      const r = await apiPatch<{ group: Group }>(`/api/groups/${groupId}`, {
        name: name.trim(),
        description: description.trim(),
        visibility,
        join_domain: visibility === "open" ? joinDomain.trim() : "",
      });
      setGroup(r.group);
      setSavedTick(Date.now());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save.");
    } finally {
      setSavingDetails(false);
    }
  }, [groupId, name, description, visibility, joinDomain]);

  const inviteUrl = useMemo(() => {
    if (!group?.invite_token || !group?.slug) return null;
    if (typeof window === "undefined") return null;
    return `${window.location.origin}/g/${group.slug}/${group.invite_token}`;
  }, [group?.invite_token, group?.slug]);

  const handleCopyInvite = useCallback(async () => {
    if (!inviteUrl) return;
    try {
      await navigator.clipboard.writeText(inviteUrl);
      setInviteCopied(true);
      window.setTimeout(() => setInviteCopied(false), 1800);
    } catch {
      /* clipboard blocked — UI shows the URL inline anyway */
    }
  }, [inviteUrl]);

  const handleRotateInvite = useCallback(async () => {
    if (!groupId) return;
    setRotating(true);
    try {
      const r = await apiPost<{ invite_token: string; slug: string }>(
        `/api/groups/${groupId}/invite`,
        {},
      );
      setGroup((prev) => (prev ? { ...prev, invite_token: r.invite_token } : prev));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't rotate the invite.");
    } finally {
      setRotating(false);
    }
  }, [groupId]);

  const handleChangeRole = useCallback(
    async (memberUid: string, role: "member" | "admin") => {
      if (!groupId) return;
      try {
        await apiPatch(`/api/groups/${groupId}/members/${memberUid}`, { role });
        await fetchAll();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Couldn't update role.");
      }
    },
    [groupId, fetchAll],
  );

  // Optimistic flip on the local roster, with a rollback if the PATCH
  // fails. Avoids a full refetch on every toggle — that would feel laggy.
  const handleTogglePermission = useCallback(
    async (memberUid: string, key: string, next: boolean) => {
      if (!groupId) return;
      const prev = members;
      setMembers((cur) =>
        cur.map((m) =>
          m.user_id === memberUid
            ? { ...m, permissions: { ...m.permissions, [key]: next } }
            : m,
        ),
      );
      try {
        await apiPatch(`/api/groups/${groupId}/members/${memberUid}`, {
          permissions: { [key]: next },
        });
      } catch (e) {
        setMembers(prev);
        setError(e instanceof Error ? e.message : "Couldn't update permission.");
      }
    },
    [groupId, members],
  );

  const [expandedUid, setExpandedUid] = useState<string | null>(null);

  // Owner-transfer is a one-way action — confirm twice to make sure
  // the current owner really wants to lose admin-level control. After
  // success the page redirects to the chat view so the new owner sees
  // their elevated UI on next load.
  const handleTransferOwner = useCallback(
    async (memberUid: string, memberName: string) => {
      if (!groupId) return;
      const ok = window.confirm(
        `Transfer ownership to ${memberName}? You'll become an admin and lose owner-only powers (archive, transfer, danger-zone actions).`,
      );
      if (!ok) return;
      try {
        await apiPost(`/api/groups/${groupId}/transfer-owner`, {
          new_owner_user_id: memberUid,
        });
        router.push(`/dashboard/groups/${groupId}`);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Couldn't transfer ownership.");
      }
    },
    [groupId, router],
  );

  const handleRemoveMember = useCallback(
    async (memberUid: string) => {
      if (!groupId) return;
      const target = members.find((m) => m.user_id === memberUid);
      const label = target ? target.display_name : "this member";
      if (!window.confirm(`Remove ${label} from the group?`)) return;
      try {
        await apiDelete(`/api/groups/${groupId}/members/${memberUid}`);
        await fetchAll();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Couldn't remove member.");
      }
    },
    [groupId, members, fetchAll],
  );

  const handleArchive = useCallback(async () => {
    if (!groupId) return;
    if (!window.confirm("Archive this group? Members can no longer see it. Data is retained.")) return;
    try {
      await apiDelete(`/api/groups/${groupId}`);
      router.push("/dashboard/groups");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't archive.");
    }
  }, [groupId, router]);

  if (notFound) {
    return (
      <div style={{ maxWidth: 560, margin: "80px auto", padding: "0 24px", textAlign: "center" }}>
        <h1 className="display-m" style={{ marginBottom: 8 }}>Group not found.</h1>
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

  if (!canManage) {
    return (
      <div style={{ maxWidth: 560, margin: "80px auto", padding: "0 24px", textAlign: "center" }}>
        <h1 className="display-m" style={{ marginBottom: 8 }}>You can&rsquo;t manage this group.</h1>
        <p style={{ color: "var(--text-secondary)", margin: "0 0 18px" }}>
          Only owners and admins can change settings or invite members.
        </p>
        <Link href={`/dashboard/groups/${groupId}`}>
          <Button variant="secondary" leftIcon={<ArrowLeft size={14} strokeWidth={1.8} />}>
            Back to the room
          </Button>
        </Link>
      </div>
    );
  }

  return (
    <div className="group-settings-shell">
      <header className="group-settings-header">
        <Link href={`/dashboard/groups/${groupId}`} className="group-back">
          <ArrowLeft size={16} strokeWidth={1.8} />
        </Link>
        <div>
          <h1 className="display-s" style={{ margin: 0 }}>{group.name}</h1>
          <p style={{ color: "var(--text-muted)", fontSize: 12.5, margin: "2px 0 0" }}>
            Group settings
          </p>
        </div>
      </header>

      {error && (
        <div className="groups-error" style={{ marginBottom: 18 }}>
          <span>{error}</span>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setError(null)}>
            Dismiss
          </button>
        </div>
      )}

      <section className="group-settings-card">
        <h2 className="group-settings-h2">Details</h2>

        <label className="modal-label" htmlFor="gs-name">Name</label>
        <input
          id="gs-name"
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={80}
        />

        <label className="modal-label" htmlFor="gs-desc" style={{ marginTop: 12 }}>Description</label>
        <textarea
          id="gs-desc"
          className="input"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          maxLength={500}
          style={{ resize: "vertical" }}
        />

        <fieldset className="modal-fieldset" style={{ marginTop: 12 }}>
          <legend className="modal-label">Visibility</legend>
          <label className="modal-radio">
            <input
              type="radio"
              name="vis"
              checked={visibility === "private"}
              onChange={() => setVisibility("private")}
            />
            <span>
              <strong>Private</strong>
              <small>Only people you add or invite.</small>
            </span>
          </label>
          <label className="modal-radio">
            <input
              type="radio"
              name="vis"
              checked={visibility === "open"}
              onChange={() => setVisibility("open")}
            />
            <span>
              <strong>Open</strong>
              <small>Anyone with the invite link can join.</small>
            </span>
          </label>
        </fieldset>

        {visibility === "open" && (
          <div style={{ marginTop: 14 }}>
            <label className="modal-label" htmlFor="gs-domain">
              Auto-join domain <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>· optional</span>
            </label>
            <input
              id="gs-domain"
              className="input"
              value={joinDomain}
              onChange={(e) => setJoinDomain(e.target.value)}
              placeholder="acme.com"
              maxLength={120}
            />
            <p style={{ margin: "6px 0 0", fontSize: 11.5, color: "var(--text-muted)", lineHeight: 1.5 }}>
              Users with a matching email get a one-click join prompt on /dashboard/groups.
              Leave blank to disable.
            </p>
          </div>
        )}

        <div style={{ marginTop: 16, display: "flex", alignItems: "center", gap: 12 }}>
          <Button onClick={() => void handleSaveDetails()} disabled={savingDetails}>
            {savingDetails ? "Saving…" : "Save details"}
          </Button>
          {savedTick > 0 && !savingDetails && (
            <span style={{ color: "var(--text-muted)", fontSize: 12.5 }}>
              Saved.
            </span>
          )}
        </div>
      </section>

      <section className="group-settings-card">
        <h2 className="group-settings-h2">Invite link</h2>
        <p style={{ color: "var(--text-secondary)", fontSize: 13, margin: "0 0 12px" }}>
          Anyone with this link can preview the group; only signed-in users can join.
          Rotate it to revoke the old link.
        </p>
        <div className="invite-row">
          <code className="invite-url">{inviteUrl || "—"}</code>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => void handleCopyInvite()}
            disabled={!inviteUrl}
          >
            {inviteCopied ? <Check size={13} strokeWidth={2} /> : <Copy size={13} strokeWidth={1.8} />}
            {inviteCopied ? "Copied" : "Copy"}
          </button>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => void handleRotateInvite()}
            disabled={rotating}
          >
            <RefreshCw size={13} strokeWidth={1.8} />
            {rotating ? "Rotating…" : "Rotate"}
          </button>
        </div>
      </section>

      <section className="group-settings-card">
        <h2 className="group-settings-h2">Members <span className="muted">· {members.length}</span></h2>
        <ul className="group-roster-list">
          {members.map((m) => {
            const isSelf = m.user_id === user?.id;
            const expanded = expandedUid === m.user_id;
            const isOwnerRow = m.role === "owner";
            return (
              <li key={m.user_id} className="group-member-li">
                <div className="group-member-row">
                  <Avatar
                    size="sm"
                    name={m.display_name}
                    src={m.avatar_url || undefined}
                    variant="accent"
                  />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="group-roster-name">
                      {m.display_name}
                      {isSelf && <span className="group-roster-you">you</span>}
                    </div>
                    <div className="group-roster-role">{m.role}</div>
                  </div>
                  <div className="group-member-actions">
                    {!isOwnerRow && (
                      <button
                        type="button"
                        className={`btn btn-secondary btn-sm ${expanded ? "is-active" : ""}`}
                        onClick={() =>
                          setExpandedUid(expanded ? null : m.user_id)
                        }
                        aria-expanded={expanded}
                        title="Per-member permissions"
                      >
                        Permissions
                        <ChevronDown
                          size={12}
                          strokeWidth={1.8}
                          style={{
                            transform: expanded ? "rotate(180deg)" : "none",
                            transition: "transform 160ms",
                          }}
                        />
                      </button>
                    )}
                    {!isOwnerRow && (
                      <>
                        {isOwner && m.role === "admin" && (
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            onClick={() => void handleTransferOwner(m.user_id, m.display_name)}
                            title="Transfer ownership of this group"
                          >
                            <Crown size={12} strokeWidth={1.8} /> Make owner
                          </button>
                        )}
                        {m.role === "admin" ? (
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            onClick={() => void handleChangeRole(m.user_id, "member")}
                            title="Demote to member"
                          >
                            <UserIcon size={12} strokeWidth={1.8} /> Demote
                          </button>
                        ) : (
                          isOwner && (
                            <button
                              type="button"
                              className="btn btn-secondary btn-sm"
                              onClick={() => void handleChangeRole(m.user_id, "admin")}
                              title="Promote to admin"
                            >
                              <Shield size={12} strokeWidth={1.8} /> Make admin
                            </button>
                          )
                        )}
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm btn-danger-quiet"
                          onClick={() => void handleRemoveMember(m.user_id)}
                          title="Remove from group"
                        >
                          <Trash2 size={12} strokeWidth={1.8} /> Remove
                        </button>
                      </>
                    )}
                  </div>
                </div>
                {expanded && !isOwnerRow && (
                  <MemberPermissionsPanel
                    member={m}
                    onToggle={(key, val) =>
                      void handleTogglePermission(m.user_id, key, val)
                    }
                  />
                )}
              </li>
            );
          })}
        </ul>
      </section>

      <ActivityPanel groupId={groupId || ""} canSeeAll={canManage} />

      {isOwner && (
        <section className="group-settings-card group-danger-zone">
          <h2 className="group-settings-h2">Danger zone</h2>
          <p style={{ color: "var(--text-secondary)", fontSize: 13, margin: "0 0 12px" }}>
            Archiving hides the group from everyone — messages are kept but no one can post.
            There&rsquo;s no undo from the UI.
          </p>
          <Button variant="destructive" onClick={() => void handleArchive()} leftIcon={<Trash2 size={14} strokeWidth={1.8} />}>
            Archive group
          </Button>
        </section>
      )}
    </div>
  );
}

// Wording note: every toggle here is the ASKER's permission — what THIS
// member is allowed to learn about other members' principals when they
// @-mention them in the room. Targets' privacy preferences are implicit
// in the group owner's choice of who has which toggle on.
const PERM_TOGGLES: Array<{
  key: "can_see_brief" | "can_query_calendar" | "can_post";
  label: string;
  help: string;
}> = [
  {
    key: "can_see_brief",
    label: "See briefs of mentioned members",
    help:
      "When this member @mentions someone, that persona may share specifics from its principal's brief. Otherwise the reply is kept high-level.",
  },
  {
    key: "can_query_calendar",
    label: "Check calendars of mentioned members",
    help:
      "Allow this member's @mentions to query the target persona's free/busy availability.",
  },
  {
    key: "can_post",
    label: "Post messages",
    help:
      "Turn off to mute this member without removing them from the group.",
  },
];

function MemberPermissionsPanel({
  member,
  onToggle,
}: {
  member: Member;
  onToggle: (key: string, next: boolean) => void;
}) {
  const perms = member.permissions || {};
  return (
    <div className="group-member-perms">
      {PERM_TOGGLES.map((t) => {
        const checked = perms[t.key] === true;
        return (
          <label key={t.key} className="group-perm-row">
            <input
              type="checkbox"
              checked={checked}
              onChange={(e) => onToggle(t.key, e.target.checked)}
            />
            <span className="group-perm-text">
              <strong>{t.label}</strong>
              <small>{t.help}</small>
            </span>
          </label>
        );
      })}
    </div>
  );
}

// ── Activity / audit log (phase 5) ────────────────────────────────
interface AuditEvent {
  id: string;
  kind: "brief_shared" | "calendar_queried";
  affected_user_id: string;
  actor_user_id: string | null;
  actor_name: string;
  affected_name: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

const AUDIT_LABEL: Record<AuditEvent["kind"], string> = {
  brief_shared: "Your brief was shared",
  calendar_queried: "Your calendar was checked",
};

function ActivityPanel({
  groupId,
  canSeeAll,
}: {
  groupId: string;
  canSeeAll: boolean;
}) {
  const [scope, setScope] = useState<"me" | "all">("me");
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!groupId) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const r = await apiGet<{ events: AuditEvent[] }>(
          `/api/groups/${groupId}/activity?scope=${scope}&limit=50`,
        );
        if (cancelled) return;
        setEvents(r.events);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Couldn't load activity.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [groupId, scope]);

  return (
    <section className="group-settings-card">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <h2 className="group-settings-h2" style={{ margin: 0 }}>Activity</h2>
        {canSeeAll && (
          <div className="group-rail-tabs" style={{ marginBottom: 0 }}>
            <button
              type="button"
              className={`group-rail-tab ${scope === "me" ? "is-active" : ""}`}
              onClick={() => setScope("me")}
            >
              My data
            </button>
            <button
              type="button"
              className={`group-rail-tab ${scope === "all" ? "is-active" : ""}`}
              onClick={() => setScope("all")}
            >
              Whole group
            </button>
          </div>
        )}
      </div>
      <p style={{ margin: "8px 0 12px", fontSize: 12.5, color: "var(--text-secondary)", lineHeight: 1.5 }}>
        {scope === "me"
          ? "When other members' actions touched your brief or calendar in this group."
          : "Recent privacy-sensitive reads across all members."}
      </p>
      {loading ? (
        <p style={{ color: "var(--text-muted)", fontSize: 13 }}>Loading…</p>
      ) : error ? (
        <div className="group-composer-error">{error}</div>
      ) : events.length === 0 ? (
        <p style={{ color: "var(--text-muted)", fontSize: 13, fontStyle: "italic" }}>
          Nothing yet. Receipts appear here when someone @mentions a member with brief access, or runs a calendar check.
        </p>
      ) : (
        <ul className="group-activity-list">
          {events.map((e) => (
            <li key={e.id} className="group-activity-row">
              <span
                className={`group-activity-dot kind-${e.kind === "brief_shared" ? "fact" : "voice"}`}
                aria-hidden
              />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="group-activity-line">
                  {scope === "me" ? (
                    <>
                      <strong>{AUDIT_LABEL[e.kind]}</strong> with{" "}
                      <span className="group-activity-actor">{e.actor_name}</span>
                    </>
                  ) : (
                    <>
                      <strong>{e.actor_name}</strong>{" "}
                      {e.kind === "brief_shared" ? "saw" : "checked"}{" "}
                      <strong>{e.affected_name}</strong>&rsquo;s{" "}
                      {e.kind === "brief_shared" ? "brief" : "calendar"}
                    </>
                  )}
                </div>
                <div className="group-activity-time">{formatActivityTime(e.created_at)}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function formatActivityTime(iso: string): string {
  try {
    const then = new Date(iso).getTime();
    const now = Date.now();
    const diff = Math.max(0, now - then);
    const mins = Math.floor(diff / 60_000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins} min ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours} h ago`;
    const days = Math.floor(hours / 24);
    if (days < 7) return `${days} d ago`;
    return new Date(iso).toLocaleDateString([], { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}
