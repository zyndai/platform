"use client";

import { useCallback, useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { apiDelete, apiGet, apiPost } from "@/lib/api";
import { getSupabase } from "@/lib/supabase";

interface Todo {
  id: string;
  title: string;
  source_text: string | null;
  done: boolean;
  done_at: string | null;
  created_at: string;
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
          EXTRACTED FROM YOUR BRIEF
        </p>
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
            No todos yet. Add lines like
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
              <Row key={t.id} todo={t} onToggle={toggleDone} onDelete={removeTodo} />
            ))}
          </Section>
        )}

        {done.length > 0 && (
          <Section title={`DONE (${done.length})`} muted>
            {done.map((t) => (
              <Row key={t.id} todo={t} onToggle={toggleDone} onDelete={removeTodo} />
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
}: {
  todo: Todo;
  onToggle: (t: Todo) => void;
  onDelete: (t: Todo) => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
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
          accentColor: "var(--accent-teal)",
          cursor: "pointer",
        }}
      />
      <span
        style={{
          flex: 1,
          color: "var(--text-primary)",
          fontFamily: "DM Sans, sans-serif",
          fontSize: "13px",
          textDecoration: todo.done ? "line-through" : "none",
        }}
      >
        {todo.title}
      </span>
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
        }}
      >
        ✕
      </button>
    </div>
  );
}
