"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Users, Plus, ArrowRight, Lock, Globe2 } from "lucide-react";
import { Button, EmptyState } from "@/components/ui";
import { useDashboard } from "@/contexts/DashboardContext";
import { apiGet, apiPost } from "@/lib/api";

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

export default function GroupsListPage() {
  const { user } = useDashboard();
  const router = useRouter();
  const [groups, setGroups] = useState<GroupSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

  const fetchGroups = useCallback(async () => {
    if (!user) return;
    try {
      const data = await apiGet<{ groups: GroupSummary[] }>("/api/groups/");
      setGroups(data.groups);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load groups.");
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await apiGet<{ groups: GroupSummary[] }>("/api/groups/");
        if (cancelled) return;
        setGroups(data.groups);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Couldn't load groups.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user]);

  const handleCreate = useCallback(
    async (payload: { name: string; description: string; visibility: "private" | "open" }) => {
      setCreating(true);
      try {
        const data = await apiPost<{ group: GroupSummary }>("/api/groups/", payload);
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

  return (
    <div style={{ maxWidth: 880, margin: "0 auto", padding: "40px 32px 56px", width: "100%" }}>
      <header
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 16,
          marginBottom: 24,
          flexWrap: "wrap",
        }}
      >
        <div>
          <h1 className="display-m" style={{ margin: "0 0 8px" }}>Groups</h1>
          <p style={{ margin: 0, color: "var(--text-secondary)", fontSize: 15, lineHeight: 1.55 }}>
            Small rooms — 3 to 15 personas — that share updates inside the group but stay invisible to the rest of the network.
          </p>
        </div>
        <Button onClick={() => setCreateOpen(true)} leftIcon={<Plus size={15} strokeWidth={1.8} />}>
          New group
        </Button>
      </header>

      {error && (
        <div className="groups-error">
          <span>{error}</span>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => void fetchGroups()}>
            Retry
          </button>
        </div>
      )}

      {loading ? (
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
      ) : groups.length === 0 ? (
        <EmptyState
          illustration={<Users />}
          title="No groups yet."
          body="Create a group for your team, a project, or a small circle of personas. Members can chat and (soon) ask each other&rsquo;s personas for updates."
          action={
            <Button onClick={() => setCreateOpen(true)} leftIcon={<Plus size={15} strokeWidth={1.8} />}>
              Create your first group
            </Button>
          }
        />
      ) : (
        <ul className="groups-list">
          {groups.map((g) => (
            <li key={g.id} className="groups-row">
              <Link href={`/dashboard/groups/${g.id}`} className="groups-row-link">
                <span className="groups-avatar" aria-hidden>
                  {g.avatar_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={g.avatar_url} alt="" />
                  ) : (
                    <span>{(g.name || "?").charAt(0).toUpperCase()}</span>
                  )}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="groups-row-name">
                    {g.name}
                    <span className={`groups-vis groups-vis-${g.visibility}`}>
                      {g.visibility === "private" ? (
                        <>
                          <Lock size={10} strokeWidth={2} /> Private
                        </>
                      ) : (
                        <>
                          <Globe2 size={10} strokeWidth={2} /> Open
                        </>
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
              <small>Anyone with the invite link can join.</small>
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
