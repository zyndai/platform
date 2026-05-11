"use client";

import { useEffect, useState } from "react";
import { apiDelete, apiGet } from "@/lib/api";
import { getSupabase } from "@/lib/supabase";

interface Todo {
  id: string;
  title: string;
  source_text: string | null;
  done: boolean;
  done_at: string | null;
  created_at: string;
}

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function TodosPanel() {
  const [todos, setTodos] = useState<Todo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTodos = async () => {
    try {
      const data = await apiGet<{ todos: Todo[] }>("/api/todos/");
      setTodos(data.todos);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load todos.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTodos();
  }, []);

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
      <div style={{ padding: "16px 24px 0" }}>
        <p className="section-label">EXTRACTED FROM YOUR BRIEF</p>
      </div>

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
