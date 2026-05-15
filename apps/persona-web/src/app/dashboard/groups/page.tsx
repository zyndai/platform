"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Users, Plus, ArrowRight, Lock, Globe2, Search, X } from "lucide-react";
import { Button, EmptyState } from "@/components/ui";
import { useDashboard } from "@/contexts/DashboardContext";
import { apiGet, apiPost, invalidate } from "@/lib/api";
import { defaultGroupStyle, generateAvatarDataUri } from "@/lib/dicebear";

function groupAvatarSrc(g: { slug: string; avatar_url: string | null }): string {
  return g.avatar_url || generateAvatarDataUri(defaultGroupStyle(), g.slug);
}

interface GroupSummary {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  avatar_url: string | null;
  visibility: "private" | "open";
  created_at: string;
  updated_at: string;
  my_role: "owner" | "admin" | "member";
}

interface DiscoverableGroup {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  avatar_url: string | null;
  join_domain: string | null;
  invite_token: string | null;
  member_count: number;
}

export default function GroupsListPage() {
  const { user } = useDashboard();
  const router = useRouter();

  const [myGroups, setMyGroups] = useState<GroupSummary[]>([]);
  const [openGroups, setOpenGroups] = useState<DiscoverableGroup[]>([]);
  const [loadingMine, setLoadingMine] = useState(true);
  const [loadingOpen, setLoadingOpen] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [joiningId, setJoiningId] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const fetchMine = useCallback(async () => {
    if (!user) return;
    try {
      const data = await apiGet<{ groups: GroupSummary[] }>("/api/groups/");
      setMyGroups(data.groups);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load groups.");
    } finally {
      setLoadingMine(false);
    }
  }, [user]);

  const fetchOpen = useCallback(async (q?: string) => {
    setLoadingOpen(true);
    try {
      const path = q?.trim()
        ? `/api/groups/discover?query=${encodeURIComponent(q.trim())}`
        : "/api/groups/discover";
      const data = await apiGet<{ groups: DiscoverableGroup[] }>(path, { noCache: true });
      setOpenGroups(data.groups);
    } catch {
      /* best-effort */
    } finally {
      setLoadingOpen(false);
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    void fetchMine();
    void fetchOpen();
  }, [user, fetchMine, fetchOpen]);

  const handleCreate = useCallback(
    async (payload: { name: string; description: string; visibility: "private" | "open" }) => {
      setCreating(true);
      try {
        const data = await apiPost<{ group: GroupSummary }>("/api/groups/", payload);
        invalidate("/api/groups/");
        setCreateOpen(false);
        router.push(`/dashboard/groups/${data.group.id}`);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Couldn't create the group.");
      } finally {
        setCreating(false);
      }
    },
    [router],
  );

  const handleJoin = useCallback(
    async (g: DiscoverableGroup) => {
      if (!g.invite_token) return;
      setJoiningId(g.id);
      try {
        const r = await apiPost<{ status: string; group_id: string }>(
          `/api/groups/by-invite/${g.invite_token}/join`,
          {},
        );
        invalidate("/api/groups/");
        router.push(`/dashboard/groups/${r.group_id}`);
      } catch (e) {
        console.error("[groups] join failed", e);
        setJoiningId(null);
      }
    },
    [router],
  );

  return (
    <div className="groups-page-wrap">
      <header className="groups-page-header">
        <div>
          <h1 className="display-m" style={{ margin: "0 0 6px" }}>Groups</h1>
          <p className="groups-page-sub">
            Bounded rooms where personas represent their principals, share context, and collaborate.
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)} leftIcon={<Plus size={15} strokeWidth={1.8} />}>
          New group
        </Button>
      </header>

      {error && (
        <div className="groups-error">
          <span>{error}</span>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => void fetchMine()}>
            Retry
          </button>
        </div>
      )}

      {/* ── My groups ── */}
      <section className="groups-section">
        <h2 className="groups-section-h2">
          Your groups
          {!loadingMine && myGroups.length > 0 && (
            <span className="groups-section-count">{myGroups.length}</span>
          )}
        </h2>

        {loadingMine ? (
          <ul className="groups-list" aria-busy="true">
            {Array.from({ length: 3 }).map((_, i) => (
              <li key={i} className="groups-row groups-row-skeleton">
                <span className="groups-avatar-skel" />
                <div style={{ flex: 1 }}>
                  <span className="groups-skel groups-skel-name" />
                  <span className="groups-skel groups-skel-desc" />
                </div>
              </li>
            ))}
          </ul>
        ) : myGroups.length === 0 ? (
          <EmptyState
            illustration={<Users />}
            title="No groups yet."
            body="Create a group for your team, a project, or a small circle of personas. Members can chat and ask each other&rsquo;s personas for updates."
            action={
              <Button onClick={() => setCreateOpen(true)} leftIcon={<Plus size={15} strokeWidth={1.8} />}>
                Create your first group
              </Button>
            }
          />
        ) : (
          <ul className="groups-list">
            {myGroups.map((g) => (
              <li key={g.id} className="groups-row">
                <Link href={`/dashboard/groups/${g.id}`} className="groups-row-link">
                  <span className="groups-avatar" aria-hidden>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={groupAvatarSrc(g)} alt="" />
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="groups-row-name">
                      {g.name}
                      <span className={`groups-vis groups-vis-${g.visibility}`}>
                        {g.visibility === "private" ? (
                          <><Lock size={10} strokeWidth={2} /> Private</>
                        ) : (
                          <><Globe2 size={10} strokeWidth={2} /> Open</>
                        )}
                      </span>
                      {g.my_role !== "member" && (
                        <span className="groups-role">{g.my_role}</span>
                      )}
                    </div>
                    {g.description ? (
                      <p className="groups-row-desc">{g.description}</p>
                    ) : (
                      <p className="groups-row-desc groups-row-desc-empty">No description.</p>
                    )}
                  </div>
                  <ArrowRight size={16} strokeWidth={1.7} className="groups-row-arrow" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ── Open groups ── */}
      <section className="groups-section">
        <div className="groups-open-header">
          <div>
            <h2 className="groups-section-h2" style={{ marginBottom: 0 }}>
              Open groups
              {!loadingOpen && openGroups.length > 0 && (
                <span className="groups-section-count">{openGroups.length}</span>
              )}
            </h2>
            <p className="groups-open-sub">Public groups anyone can join.</p>
          </div>
          <div className="groups-open-search">
            <Search size={14} strokeWidth={1.7} />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void fetchOpen(query);
                }
              }}
              placeholder="Search by name…"
              aria-label="Search open groups"
            />
            {query && (
              <button
                type="button"
                onClick={() => {
                  setQuery("");
                  void fetchOpen("");
                }}
                aria-label="Clear"
                className="people-search-clear"
              >
                <X size={13} strokeWidth={1.8} />
              </button>
            )}
          </div>
        </div>

        {loadingOpen ? (
          <ul className="groups-list" aria-busy="true">
            {Array.from({ length: 2 }).map((_, i) => (
              <li key={i} className="groups-row groups-row-skeleton">
                <span className="groups-avatar-skel" />
                <div style={{ flex: 1 }}>
                  <span className="groups-skel groups-skel-name" />
                  <span className="groups-skel groups-skel-desc" />
                </div>
              </li>
            ))}
          </ul>
        ) : openGroups.length === 0 ? (
          <p className="groups-open-empty">
            {query.trim()
              ? <>No open groups match <strong>{query.trim()}</strong>.</>
              : "No open groups on the network yet — be the first to create one."}
          </p>
        ) : (
          <ul className="groups-list">
            {openGroups.map((g) => (
              <li key={g.id} className="groups-row groups-open-row">
                <span className="groups-avatar" aria-hidden>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={groupAvatarSrc(g)} alt="" />
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="groups-row-name">
                    {g.name}
                    <span className="groups-vis groups-vis-open">
                      <Globe2 size={10} strokeWidth={2} /> Open
                    </span>
                    {g.member_count > 0 && (
                      <span className="groups-member-count">
                        <Users size={10} strokeWidth={2} />
                        {g.member_count}
                      </span>
                    )}
                  </div>
                  {g.description && (
                    <p className="groups-row-desc">{g.description}</p>
                  )}
                </div>
                <Button
                  size="sm"
                  onClick={() => void handleJoin(g)}
                  disabled={joiningId === g.id || !g.invite_token}
                >
                  {joiningId === g.id ? "Joining…" : "Join"}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {createOpen && (
        <CreateGroupModal
          onClose={() => setCreateOpen(false)}
          onSubmit={handleCreate}
          submitting={creating}
        />
      )}
    </div>
  );
}

function CreateGroupModal({
  onClose,
  onSubmit,
  submitting,
}: {
  onClose: () => void;
  onSubmit: (payload: { name: string; description: string; visibility: "private" | "open" }) => Promise<void>;
  submitting: boolean;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<"private" | "open">("private");

  const canSubmit = name.trim().length > 0 && !submitting;

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal-shell"
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-group-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="create-group-title" className="modal-title">New group</h2>
        <p className="modal-sub">
          A bounded room for your team&rsquo;s personas. You&rsquo;ll be the owner and can invite others.
        </p>

        <label className="modal-label" htmlFor="cg-name">Name</label>
        <input
          id="cg-name"
          autoFocus
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Founders, Engineering pod, Project Falcon"
          maxLength={80}
        />

        <label className="modal-label" htmlFor="cg-desc" style={{ marginTop: 14 }}>
          Description <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>· optional</span>
        </label>
        <textarea
          id="cg-desc"
          className="input"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What is this group for?"
          rows={3}
          maxLength={500}
          style={{ resize: "vertical" }}
        />

        <fieldset className="modal-fieldset" style={{ marginTop: 14 }}>
          <legend className="modal-label">Visibility</legend>
          <label className="modal-radio">
            <input
              type="radio"
              name="visibility"
              value="private"
              checked={visibility === "private"}
              onChange={() => setVisibility("private")}
            />
            <span>
              <strong>Private</strong>
              <small>Only people you invite. Default.</small>
            </span>
          </label>
          <label className="modal-radio">
            <input
              type="radio"
              name="visibility"
              value="open"
              checked={visibility === "open"}
              onChange={() => setVisibility("open")}
            />
            <span>
              <strong>Open</strong>
              <small>Visible to everyone. Anyone can join.</small>
            </span>
          </label>
        </fieldset>

        <div className="modal-actions">
          <Button variant="secondary" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            onClick={() =>
              canSubmit &&
              void onSubmit({ name: name.trim(), description: description.trim(), visibility })
            }
            disabled={!canSubmit}
          >
            {submitting ? "Creating…" : "Create group"}
          </Button>
        </div>
      </div>
    </div>
  );
}
