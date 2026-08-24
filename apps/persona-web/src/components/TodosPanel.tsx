"use client";

import { useCallback, useEffect, useState } from "react";
import { Sparkles, Plus } from "lucide-react";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { getSupabase } from "@/lib/supabase";

interface Todo {
  id: string;
  title: string;
  source_text: string | null;
  done: boolean;
  done_at: string | null;
  created_at: string;
  group_id?: string | null;
  group_name?: string | null;
  assigned_by_user_id?: string | null;
  assigned_by_name?: string | null;
}

interface ExtractResponse {
  status: string;
  extractor: string;
  extracted_total: number;
  inserted_new: number;
}

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function TodosPanel() {
  const [todos, setTodos] = useState<Todo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [extractMsg, setExtractMsg] = useState<string | null>(null);
  const [autoExtract, setAutoExtract] = useState(true);
  const [togglingAuto, setTogglingAuto] = useState(false);
  const [addingTitle, setAddingTitle] = useState("");
  const [adding, setAdding] = useState(false);

  const fetchTodos = useCallback(async () => {
    try {
      const data = await apiGet<{ todos: Todo[] }>("/api/todos/");
      setTodos(data.todos);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load todos.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchTodos();
  }, [fetchTodos]);

  useEffect(() => {
    apiGet<{ auto_extract: boolean }>("/api/todos/settings")
      .then((data) => setAutoExtract(data.auto_extract))
      .catch(() => {
        // No active persona yet, or table not migrated — default stays true.
      });
  }, []);

  const handleToggleAutoExtract = useCallback(async () => {
    const next = !autoExtract;
    setAutoExtract(next);
    setTogglingAuto(true);
    try {
      await apiPatch<{ auto_extract: boolean }>("/api/todos/settings", {
        auto_extract: next,
      });
    } catch (err) {
      setAutoExtract(!next);
      setExtractMsg(
        err instanceof Error ? err.message : "Couldn't update the setting.",
      );
    } finally {
      setTogglingAuto(false);
    }
  }, [autoExtract]);

  const handleAddTodo = useCallback(async () => {
    const title = addingTitle.trim();
    if (!title) return;
    setAdding(true);
    try {
      const todo = await apiPost<Todo>("/api/todos/", { title });
      setTodos((prev) => [todo, ...prev]);
      setAddingTitle("");
    } catch (err) {
      setExtractMsg(err instanceof Error ? err.message : "Couldn't add todo.");
    } finally {
      setAdding(false);
    }
  }, [addingTitle]);

  const handleExtractNow = useCallback(async () => {
    setExtracting(true);
    setExtractMsg(null);
    try {
      const data = await apiPost<ExtractResponse>("/api/todos/extract", {});
      await fetchTodos();
      if (data.inserted_new === 0) {
        setExtractMsg(
          data.extracted_total === 0
            ? "Nothing actionable in your brief yet — try adding what you're working on."
            : "Your brief is already in sync — no new todos found.",
        );
      } else {
        setExtractMsg(
          `Added ${data.inserted_new} new todo${data.inserted_new === 1 ? "" : "s"} from your brief.`,
        );
      }
    } catch (err) {
      setExtractMsg(
        err instanceof Error ? err.message : "Couldn't extract right now.",
      );
    } finally {
      setExtracting(false);
    }
  }, [fetchTodos]);

  // Clear the extract status message after a short delay so it doesn't linger.
  useEffect(() => {
    if (!extractMsg) return;
    const t = setTimeout(() => setExtractMsg(null), 5000);
    return () => clearTimeout(t);
  }, [extractMsg]);

  // PATCH helper that does an optimistic toggle on the local list, then rolls
  // back on failure so the UI doesn't lie about the persisted state.
  const toggleDone = async (todo: Todo) => {
    const next = !todo.done;
    setTodos((prev) =>
      prev.map((t) => (t.id === todo.id ? { ...t, done: next } : t))
    );
    try {
      const sb = getSupabase();
      const {
        data: { session },
      } = await sb.auth.getSession();
      const res = await fetch(`${API}/api/todos/${todo.id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          ...(session?.access_token
            ? { Authorization: `Bearer ${session.access_token}` }
            : {}),
        },
        body: JSON.stringify({ done: next }),
      });
      if (!res.ok) throw new Error(await res.text());
    } catch {
      setTodos((prev) =>
        prev.map((t) => (t.id === todo.id ? { ...t, done: !next } : t))
      );
    }
  };

  const removeTodo = async (todo: Todo) => {
    setTodos((prev) => prev.filter((t) => t.id !== todo.id));
    try {
      await apiDelete(`/api/todos/${todo.id}`);
    } catch {
      // Roll back if delete failed.
      setTodos((prev) => [...prev, todo]);
    }
  };

  const renameTodo = async (todo: Todo, title: string) => {
    const prevTitle = todo.title;
    setTodos((prev) =>
      prev.map((t) => (t.id === todo.id ? { ...t, title } : t))
    );
    try {
      await apiPatch(`/api/todos/${todo.id}`, { title });
    } catch (err) {
      setTodos((prev) =>
        prev.map((t) => (t.id === todo.id ? { ...t, title: prevTitle } : t))
      );
      setExtractMsg(err instanceof Error ? err.message : "Couldn't rename todo.");
    }
  };

  const open = todos.filter((t) => !t.done);
  const done = todos.filter((t) => t.done);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        flex: 1,
        background: "var(--bg-base)",
      }}
    >
      <div
        style={{
          padding: "16px 24px 0",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <p className="section-label" style={{ margin: 0 }}>
          YOUR TODOS
        </p>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <label
            title="When on, your Brief is periodically re-read and new todos are added automatically"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              fontSize: 12,
              color: "var(--text-secondary)",
              cursor: togglingAuto ? "default" : "pointer",
              userSelect: "none",
            }}
          >
            Auto-extract from brief
            <span
              onClick={() => !togglingAuto && handleToggleAutoExtract()}
              style={{
                position: "relative",
                width: 32,
                height: 18,
                borderRadius: 999,
                background: autoExtract ? "var(--accent-teal)" : "var(--border-default)",
                transition: "background 0.15s ease",
                opacity: togglingAuto ? 0.6 : 1,
                flexShrink: 0,
              }}
            >
              <span
                style={{
                  position: "absolute",
                  top: 2,
                  left: autoExtract ? 16 : 2,
                  width: 14,
                  height: 14,
                  borderRadius: "50%",
                  background: "var(--bg-base)",
                  transition: "left 0.15s ease",
                }}
              />
            </span>
          </label>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={handleExtractNow}
            disabled={extracting}
            style={{
              fontSize: 12,
              padding: "6px 12px",
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
            }}
            title="Re-read your brief and extract any new todos with the LLM"
          >
            <Sparkles size={13} strokeWidth={1.8} />
            {extracting ? "Extracting…" : "Refresh from brief"}
          </button>
        </div>
      </div>

      <div
        style={{
          padding: "12px 24px 0",
          display: "flex",
          gap: 8,
        }}
      >
        <input
          type="text"
          value={addingTitle}
          onChange={(e) => setAddingTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void handleAddTodo();
          }}
          placeholder="Add a todo…"
          disabled={adding}
          style={{
            flex: 1,
            padding: "8px 12px",
            fontSize: 13,
            background: "var(--bg-surface)",
            border: "1px solid var(--border-default)",
            borderRadius: "var(--r-sm)",
            color: "var(--text-primary)",
          }}
        />
        <button
          type="button"
          className="btn btn-secondary"
          onClick={handleAddTodo}
          disabled={adding || !addingTitle.trim()}
          style={{
            fontSize: 12,
            padding: "6px 12px",
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <Plus size={13} strokeWidth={1.8} />
          Add
        </button>
      </div>
      {extractMsg && (
        <div
          style={{
            margin: "10px 24px 0",
            padding: "8px 12px",
            background: "var(--bg-surface)",
            border: "1px solid var(--border-default)",
            borderRadius: "var(--r-sm)",
            color: "var(--text-secondary)",
            fontSize: 12.5,
            lineHeight: 1.45,
          }}
        >
          {extractMsg}
        </div>
      )}

      <div style={{ flex: 1, overflowY: "auto", padding: "16px 24px 24px" }}>
        {loading && <p style={{ color: "var(--text-secondary)" }}>Loading…</p>}
        {error && <p style={{ color: "var(--text-secondary)" }}>{error}</p>}
        {!loading && !error && todos.length === 0 && (
          <div
            style={{
              border: "1px dashed var(--border-default)",
              borderRadius: "var(--r-md)",
              padding: "32px",
              textAlign: "center",
              color: "var(--text-secondary)",
            }}
          >
            No todos yet. Add one above, or add lines like
            <code
              style={{
                display: "inline-block",
                margin: "0 6px",
                padding: "2px 6px",
                background: "var(--bg-void)",
                borderRadius: "4px",
              }}
            >
              - [ ] follow up with X
            </code>
            or
            <code
              style={{
                display: "inline-block",
                margin: "0 6px",
                padding: "2px 6px",
                background: "var(--bg-void)",
                borderRadius: "4px",
              }}
            >
              TODO: ship the demo
            </code>
            to your Brief and they'll show up here within a few minutes.
          </div>
        )}

        {open.length > 0 && (
          <Section title={`OPEN (${open.length})`}>
            {open.map((t) => (
              <Row
                key={t.id}
                todo={t}
                onToggle={toggleDone}
                onDelete={removeTodo}
                onRename={renameTodo}
              />
            ))}
          </Section>
        )}

        {done.length > 0 && (
          <Section title={`DONE (${done.length})`} muted>
            {done.map((t) => (
              <Row
                key={t.id}
                todo={t}
                onToggle={toggleDone}
                onDelete={removeTodo}
                onRename={renameTodo}
              />
            ))}
          </Section>
        )}
      </div>
    </div>
  );
}

function Section({
  title,
  children,
  muted,
}: {
  title: string;
  children: React.ReactNode;
  muted?: boolean;
}) {
  return (
    <div style={{ marginBottom: "20px", opacity: muted ? 0.65 : 1 }}>
      <p className="section-label" style={{ marginBottom: "10px" }}>
        {title}
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
        {children}
      </div>
    </div>
  );
}

function Row({
  todo,
  onToggle,
  onDelete,
  onRename,
}: {
  todo: Todo;
  onToggle: (t: Todo) => void;
  onDelete: (t: Todo) => void;
  onRename: (t: Todo, title: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(todo.title);

  useEffect(() => {
    if (!editing) setDraft(todo.title);
  }, [todo.title, editing]);

  const commit = () => {
    setEditing(false);
    const title = draft.trim();
    if (title && title !== todo.title) onRename(todo, title);
    else setDraft(todo.title);
  };

  const hasMeta = Boolean(todo.group_name || todo.assigned_by_name);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: "12px",
        background: "var(--bg-surface)",
        border: "1px solid var(--border-default)",
        borderRadius: "var(--r-sm)",
        padding: "10px 14px",
      }}
    >
      <input
        type="checkbox"
        checked={todo.done}
        onChange={() => onToggle(todo)}
        style={{
          width: "16px",
          height: "16px",
          marginTop: "2px",
          accentColor: "var(--accent-teal)",
          cursor: "pointer",
          flexShrink: 0,
        }}
      />
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: "3px" }}>
        {editing ? (
          <input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === "Enter") commit();
              if (e.key === "Escape") {
                setDraft(todo.title);
                setEditing(false);
              }
            }}
            style={{
              fontFamily: "DM Sans, sans-serif",
              fontSize: "13px",
              color: "var(--text-primary)",
              background: "var(--bg-base)",
              border: "1px solid var(--border-default)",
              borderRadius: "4px",
              padding: "2px 6px",
            }}
          />
        ) : (
          <span
            onClick={() => setEditing(true)}
            title="Click to edit"
            style={{
              color: "var(--text-primary)",
              fontFamily: "DM Sans, sans-serif",
              fontSize: "13px",
              textDecoration: todo.done ? "line-through" : "none",
              cursor: "text",
            }}
          >
            {todo.title}
          </span>
        )}
        {hasMeta && (
          <span
            style={{
              fontSize: "11.5px",
              color: "var(--text-secondary)",
            }}
          >
            {todo.assigned_by_name && <>Assigned by: {todo.assigned_by_name}</>}
            {todo.assigned_by_name && todo.group_name && "  |  "}
            {todo.group_name && (
              <>
                Group: <strong style={{ color: "var(--text-primary)" }}>{todo.group_name}</strong>
              </>
            )}
          </span>
        )}
      </div>
      <button
        onClick={() => onDelete(todo)}
        title="Remove"
        style={{
          background: "none",
          border: "1px solid var(--border-default)",
          color: "var(--text-muted)",
          cursor: "pointer",
          padding: "4px 8px",
          borderRadius: "var(--r-sm)",
          fontSize: "11px",
          flexShrink: 0,
        }}
      >
        ✕
      </button>
    </div>
  );
}
