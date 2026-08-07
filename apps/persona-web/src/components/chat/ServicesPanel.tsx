"use client";

/**
 * Inline renderer for slash-command results in the chat thread.
 *
 * Handles three payload kinds: search results, single agent-card detail,
 * and a help block. Each result row has a "View card" affordance that
 * triggers a follow-up card fetch, surfaced via the parent's onCardLookup
 * callback so the parent owns the message-list state.
 */

import { useState } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Search,
  FileCode,
  Tag,
  PhoneCall,
  Sparkles,
  Loader2,
} from "lucide-react";
import type { ServicesPanelPayload } from "./types";
import GenUiResult from "./GenUiResult";
import type {
  AgentSearchResult,
  ServiceCallResult,
  ServiceCardPayload,
  ServiceSearchResult,
} from "@/lib/services-commands";

/** Args the parent needs to open a Call form for an entity. */
export interface CallTarget {
  entityId: string;
  name?: string;
  kind?: string;
}

interface ServicesPanelProps {
  payload: ServicesPanelPayload;
  /** Called when the user clicks "View card" on a search result.
   *  The parent runs the fetch and appends a new card-payload message. */
  onCardLookup?: (entityId: string) => void;
  /** Open the Call form: parent appends a new "call"-kind message and
   *  fetches the card to drive the schema form. */
  onCallAgent?: (target: CallTarget) => void;
  /** Submit a Call form for an already-open call message. */
  onCall?: (entityId: string, args: { text?: string; data?: Record<string, unknown> }) => void;
  /** Hand the request to the LLM chat ("Let my persona handle it"). */
  onAskPersona?: (target: CallTarget & { intent?: string }) => void;
}

export default function ServicesPanel({
  payload,
  onCardLookup,
  onCallAgent,
  onCall,
  onAskPersona,
}: ServicesPanelProps) {
  if (payload.loading) {
    return (
      <div className="services-panel services-panel-loading">
        <Search size={14} strokeWidth={1.6} />
        <span>
          {payload.kind === "search"
            ? `Searching Zynd services for "${payload.query}"…`
            : payload.kind === "agents"
              ? `Searching the Zynd Network for "${payload.query}"…`
              : payload.kind === "card"
                ? `Loading service card…`
                : "Working…"}
        </span>
      </div>
    );
  }

  if (payload.kind === "help") {
    return (
      <div className="services-panel services-panel-help">
        <div className="markdown-content">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {payload.helpText || ""}
          </ReactMarkdown>
        </div>
      </div>
    );
  }

  if (payload.kind === "error") {
    return (
      <div className="services-panel services-panel-error">
        <p>{payload.error || "Something went wrong."}</p>
      </div>
    );
  }

  if (payload.kind === "search") {
    const s = payload.search;
    if (!s) return null;
    if (s.status === "error" || (s.count === 0 && s.results.length === 0)) {
      return (
        <div className="services-panel services-panel-empty">
          <p className="services-panel-head">
            <Search size={14} strokeWidth={1.6} />
            <span>
              {s.error
                ? `Search failed`
                : `No services matched "${payload.query}"`}
            </span>
          </p>
          {(s.hint || s.error) && (
            <p className="services-panel-hint">{s.error || s.hint}</p>
          )}
        </div>
      );
    }
    return (
      <div className="services-panel services-panel-search">
        <p className="services-panel-head">
          <Search size={14} strokeWidth={1.6} />
          <span>
            {s.count} service{s.count === 1 ? "" : "s"} for{" "}
            <em>&ldquo;{payload.query}&rdquo;</em>
            {s.from_cache && (
              <span className="services-panel-cached" title="From 30s cache">
                {" "}
                · cached
              </span>
            )}
          </span>
        </p>
        <ul className="services-result-list">
          {s.results.map((r) => (
            <ServiceResultRow
              key={r.entity_id}
              result={r}
              onView={onCardLookup ? () => onCardLookup(r.entity_id) : undefined}
              onCall={
                onCallAgent
                  ? () => onCallAgent({ entityId: r.entity_id, name: r.name })
                  : undefined
              }
              onAskPersona={
                onAskPersona
                  ? () => onAskPersona({ entityId: r.entity_id, name: r.name })
                  : undefined
              }
            />
          ))}
        </ul>
      </div>
    );
  }

  if (payload.kind === "agents") {
    const a = payload.agents;
    if (!a) return null;
    const results = Array.isArray(a.results) ? a.results : [];
    if (a.status === "error" || results.length === 0) {
      return (
        <div className="services-panel services-panel-empty">
          <p className="services-panel-head">
            <Search size={14} strokeWidth={1.6} />
            <span>
              {a.error
                ? `Search failed`
                : `Nothing on the network matched "${payload.query}"`}
            </span>
          </p>
          {a.error && <p className="services-panel-hint">{a.error}</p>}
        </div>
      );
    }
    const total = a.total_available ?? results.length;
    const showingSubset = total > results.length;
    return (
      <div className="services-panel services-panel-search">
        <p className="services-panel-head">
          <Search size={14} strokeWidth={1.6} />
          <span>
            {total} result{total === 1 ? "" : "s"} on the network
            {payload.query ? (
              <>
                {" "}
                for <em>&ldquo;{payload.query}&rdquo;</em>
              </>
            ) : null}
            {showingSubset ? ` — showing top ${results.length}` : null}
          </span>
        </p>
        <ul className="services-result-list">
          {results.map((r) => (
            <AgentResultRow
              key={r.entity_id}
              result={r}
              onView={onCardLookup ? () => onCardLookup(r.entity_id) : undefined}
              onCall={
                onCallAgent
                  ? () =>
                      onCallAgent({
                        entityId: r.entity_id,
                        name: r.name,
                        kind: r.kind,
                      })
                  : undefined
              }
              onAskPersona={
                onAskPersona
                  ? () =>
                      onAskPersona({
                        entityId: r.entity_id,
                        name: r.name,
                        kind: r.kind,
                      })
                  : undefined
              }
            />
          ))}
        </ul>
      </div>
    );
  }

  if (payload.kind === "card") {
    const c = payload.card;
    if (!c) return null;
    return (
      <ServiceCardDetail
        card={c}
        onCall={
          onCallAgent
            ? () => onCallAgent({ entityId: c.entity_id, name: c.name })
            : undefined
        }
        onAskPersona={
          onAskPersona
            ? () => onAskPersona({ entityId: c.entity_id, name: c.name })
            : undefined
        }
      />
    );
  }

  if (payload.kind === "call") {
    return <CallPanel payload={payload} onCall={onCall} onAskPersona={onAskPersona} />;
  }

  return null;
}

function AgentResultRow({
  result,
  onView,
  onCall,
  onAskPersona,
}: {
  result: AgentSearchResult;
  onView?: () => void;
  onCall?: () => void;
  onAskPersona?: () => void;
}) {
  const isPersona = result.kind === "persona";
  const typeLabel = result.kind || result.entity_type || "agent";
  const typeTitle = isPersona
    ? "Human's persona — needs connection request"
    : typeLabel === "service"
      ? "Standalone service — directly callable"
      : "Standalone agent — directly callable";
  return (
    <li className="service-result-row">
      <div className="service-result-main">
        <div className="service-result-head">
          <span className="service-result-name">{result.name}</span>
          <span className={`service-result-type type-${typeLabel}`} title={typeTitle}>
            {typeLabel}
          </span>
          {/* Topic category as a secondary chip when it adds info. */}
          {result.category && result.category !== "general" && !isPersona && (
            <span className="service-result-cat">{result.category}</span>
          )}
          {result.status && result.status !== "active" && (
            <span className="service-result-status">{result.status}</span>
          )}
        </div>
        {result.summary && (
          <div className="service-result-summary">{result.summary}</div>
        )}
      </div>
      <div className="service-result-actions">
        {/* Personas need a connection handshake — no direct call. */}
        {!isPersona && onCall && (
          <button
            type="button"
            className="service-result-call"
            onClick={onCall}
            title="Fill in this agent's inputs and call it"
          >
            Call
            <PhoneCall size={12} strokeWidth={1.8} />
          </button>
        )}
        {onAskPersona && (
          <button
            type="button"
            className="service-result-ask"
            onClick={onAskPersona}
            title="Let your persona call this on your behalf"
          >
            Let my persona handle it
            <Sparkles size={12} strokeWidth={1.8} />
          </button>
        )}
        {onView && (
          <button
            type="button"
            className="service-result-view"
            onClick={onView}
            title="Fetch the full agent-card"
          >
            View card
            <FileCode size={12} strokeWidth={1.8} />
          </button>
        )}
      </div>
    </li>
  );
}

function ServiceResultRow({
  result,
  onView,
  onCall,
  onAskPersona,
}: {
  result: ServiceSearchResult;
  onView?: () => void;
  onCall?: () => void;
  onAskPersona?: () => void;
}) {
  const score =
    typeof result.score === "number" ? (result.score * 100).toFixed(0) + "%" : null;
  return (
    <li className="service-result-row">
      <div className="service-result-main">
        <div className="service-result-head">
          <span className="service-result-name">{result.name}</span>
          {result.category && (
            <span className="service-result-cat">{result.category}</span>
          )}
          {result.status && result.status !== "active" && (
            <span className="service-result-status">{result.status}</span>
          )}
          {score && (
            <span className="service-result-score" title="Relevance score">
              {score}
            </span>
          )}
        </div>
        {result.summary && (
          <div className="service-result-summary">{result.summary}</div>
        )}
      </div>
      <div className="service-result-actions">
        {onCall && (
          <button
            type="button"
            className="service-result-call"
            onClick={onCall}
            title="Fill in this service's inputs and call it"
          >
            Call
            <PhoneCall size={12} strokeWidth={1.8} />
          </button>
        )}
        {onAskPersona && (
          <button
            type="button"
            className="service-result-ask"
            onClick={onAskPersona}
            title="Let your persona call this on your behalf"
          >
            Let my persona handle it
            <Sparkles size={12} strokeWidth={1.8} />
          </button>
        )}
        {onView && (
          <button
            type="button"
            className="service-result-view"
            onClick={onView}
            title="Fetch the full agent-card"
          >
            View card
            <FileCode size={12} strokeWidth={1.8} />
          </button>
        )}
      </div>
    </li>
  );
}

function ServiceCardDetail({
  card,
  onCall,
  onAskPersona,
}: {
  card: ServiceCardPayload;
  onCall?: () => void;
  onAskPersona?: () => void;
}) {
  // The card payload has no persona/kind field — best-effort guard so we
  // don't offer a direct Call on a human's persona (which needs a
  // connection handshake). Reaching Call from a search row is more
  // reliable since that row carries the real `kind`.
  const isPersona = card.category === "persona";

  if (card.status === "not_found") {
    return (
      <div className="services-panel services-panel-empty">
        <p>
          {card.name || "That service"} is not registered on the network right now.
        </p>
      </div>
    );
  }
  if (card.status === "unreachable") {
    return (
      <div className="services-panel services-panel-empty">
        <p>
          {card.name || "That service"} is registered but its deployment is
          unreachable.
        </p>
        {/* card.hint is LLM tool-use guidance (call_zynd_service / A2A schema) —
            internal, never shown to end users. */}
      </div>
    );
  }
  if (card.status === "error") {
    return (
      <div className="services-panel services-panel-error">
        <p>{card.error || "Couldn't load the service card."}</p>
      </div>
    );
  }

  return (
    <div className="services-panel services-card-detail">
      <div className="services-card-head">
        <div>
          <div className="services-card-name">{card.name || "Service"}</div>
        </div>
        {card.category && (
          <span className="services-card-cat">
            <Tag size={11} strokeWidth={1.8} />
            {card.category}
          </span>
        )}
      </div>

      {card.description && (
        <p className="services-card-desc">{card.description}</p>
      )}

      {/* Internal implementation details (raw IDs, endpoint URLs, input schema)
          are hidden from end users. The LLM still receives them via tool results;
          the UI shows only name, description, category, and action buttons. */}

      {(onCall || onAskPersona) && (
        <div className="services-card-actions">
          {!isPersona && onCall && (
            <button type="button" className="service-result-call" onClick={onCall}>
              Call this service
              <PhoneCall size={12} strokeWidth={1.8} />
            </button>
          )}
          {onAskPersona && (
            <button type="button" className="service-result-ask" onClick={onAskPersona}>
              Let my persona handle it
              <Sparkles size={12} strokeWidth={1.8} />
            </button>
          )}
        </div>
      )}

      {/* card.hint is LLM tool-use guidance — internal, never shown to users. */}
    </div>
  );
}

// ── Call form ────────────────────────────────────────────────────────

/** Renders the schema-driven Call form for a "call"-kind message: a
 *  header, the form (once the card resolves), and the most recent result. */
function CallPanel({
  payload,
  onCall,
  onAskPersona,
}: {
  payload: ServicesPanelPayload;
  onCall?: (entityId: string, args: { text?: string; data?: Record<string, unknown> }) => void;
  onAskPersona?: (target: CallTarget & { intent?: string }) => void;
}) {
  const entityId = payload.entityId || "";
  const name = payload.callName || payload.card?.name || "Service";
  const card = payload.card;

  if (payload.callLoading || (!card && !payload.callError)) {
    return (
      <div className="services-panel services-call">
        <div className="services-panel-loading">
          <Loader2 size={14} strokeWidth={1.6} className="services-spin" />
          <span>Loading {name}&rsquo;s inputs…</span>
        </div>
      </div>
    );
  }

  if (payload.callError && !card) {
    return (
      <div className="services-panel services-panel-error">
        <p>{payload.callError}</p>
      </div>
    );
  }

  if (card && card.status !== "success") {
    // Reuse the card-detail guards for not_found / unreachable / error.
    return <ServiceCardDetail card={card} />;
  }

  const schema = card?.input_schema as
    | { properties?: Record<string, JsonSchemaProp>; required?: string[] }
    | undefined;

  return (
    <div className="services-panel services-call">
      <div className="services-call-head">
        <PhoneCall size={14} strokeWidth={1.8} />
        <span>
          Call <strong>{name}</strong>
        </span>
      </div>

      <CallForm
        schema={schema}
        submitting={!!payload.callSubmitting}
        onSubmit={(args) => onCall?.(entityId, args)}
      />

      {payload.callError && card && (
        <p className="services-panel-hint services-call-err">{payload.callError}</p>
      )}
      {payload.callResult && <CallResult result={payload.callResult} />}

      {onAskPersona && (
        <button
          type="button"
          className="service-result-ask services-call-handoff"
          onClick={() => onAskPersona({ entityId, name })}
        >
          Or let my persona handle it
          <Sparkles size={12} strokeWidth={1.8} />
        </button>
      )}
    </div>
  );
}

interface JsonSchemaProp {
  type?: string | string[];
  title?: string;
  description?: string;
  enum?: unknown[];
  format?: string;
  items?: JsonSchemaProp & { properties?: Record<string, unknown> };
  properties?: Record<string, unknown>;
}

const FREE_TEXT_KEYS = new Set(["text", "query", "input", "prompt", "message", "content"]);

function CallForm({
  schema,
  submitting,
  onSubmit,
}: {
  schema?: { properties?: Record<string, JsonSchemaProp>; required?: string[] };
  submitting?: boolean;
  onSubmit: (args: { text?: string; data?: Record<string, unknown> }) => void;
}) {
  const allProps = schema?.properties || {};
  const required = new Set(schema?.required || []);

  // Hide A2A transport/envelope plumbing — the service auto-fills these and
  // the user must never see them. These show up because many Zynd services
  // wrap their real inputs in the standard message envelope.
  const ENVELOPE_FIELDS = new Set([
    "conversation_id", "in_reply_to", "message_id", "message_type",
    "receiver_id", "sender_id", "sender_did", "sender_public_key",
    "reply_to", "thread_id", "context_id", "trace_id",
  ]);

  const primitiveType = (p: JsonSchemaProp): string => {
    const t = Array.isArray(p.type) ? p.type.find((x) => x !== "null") : p.type;
    return t || "string";
  };

  // Visible, fillable fields: drop envelope plumbing.
  const keys = Object.keys(allProps).filter((k) => !ENVELOPE_FIELDS.has(k));
  const hasProps = keys.length > 0;

  // Primary fields shown up-front: required ones, plus the obvious "main"
  // task fields. Everything else hides behind an Advanced expander so the
  // common case is one or two inputs, not fifteen.
  const PRIMARY_NAMES = new Set([
    "competitors", "query", "text", "content", "input", "prompt", "url",
    "base_url", "subject", "topic", "name", "message",
  ]);
  const primaryKeys = keys.filter((k) => required.has(k) || PRIMARY_NAMES.has(k.toLowerCase()));
  const advancedKeys = keys.filter((k) => !primaryKeys.includes(k));
  // If nothing matched as primary, show the first 2 so the form isn't empty.
  const shownPrimary = primaryKeys.length > 0 ? primaryKeys : keys.slice(0, 2);
  const restAdvanced =
    primaryKeys.length > 0 ? advancedKeys : keys.slice(2);

  const [freeText, setFreeText] = useState("");
  const [fields, setFields] = useState<Record<string, string | boolean>>({});
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [jsonError, setJsonError] = useState<string | null>(null);

  const arrayItemKey = (p: JsonSchemaProp): string | null => {
    // For an array of objects, find the single "primary" sub-field to map
    // comma-separated input onto (name → homepage → first key).
    const items = p.items as JsonSchemaProp | undefined;
    const itemProps = (items as { properties?: Record<string, unknown> })?.properties;
    if (!itemProps) return null;
    const ks = Object.keys(itemProps);
    return ks.find((x) => /^(name|title|homepage|url|id|value)$/i.test(x)) || ks[0] || null;
  };
  const isObjectArray = (p: JsonSchemaProp) =>
    primitiveType(p) === "array" && !!(p.items as { properties?: unknown })?.properties;
  const isScalarArray = (p: JsonSchemaProp) =>
    primitiveType(p) === "array" && !(p.items as { properties?: unknown })?.properties;

  const setField = (k: string, v: string | boolean) =>
    setFields((prev) => ({ ...prev, [k]: v }));

  // Split "a, b\nc" → ["a","b","c"].
  const splitList = (s: string) =>
    s.split(/[\n,]+/).map((x) => x.trim()).filter(Boolean);

  const buildData = (): { data?: Record<string, unknown>; err?: string } => {
    const out: Record<string, unknown> = {};
    for (const k of keys) {
      const p = allProps[k];
      const raw = fields[k];
      const t = primitiveType(p);
      if (t === "boolean") {
        if (raw === true) out[k] = true;
        continue;
      }
      const s = typeof raw === "string" ? raw.trim() : "";
      if (!s) continue; // omit empty fields
      if (t === "number" || t === "integer") {
        const n = Number(s);
        if (Number.isNaN(n)) return { err: `"${k}" must be a number.` };
        out[k] = n;
      } else if (isScalarArray(p)) {
        out[k] = splitList(s);
      } else if (isObjectArray(p)) {
        const itemKey = arrayItemKey(p);
        out[k] = itemKey
          ? splitList(s).map((v) => ({ [itemKey]: v }))
          : splitList(s);
      } else if (t === "object") {
        try {
          out[k] = JSON.parse(s);
        } catch {
          return { err: `"${k}" must be valid JSON.` };
        }
      } else {
        out[k] = s;
      }
    }
    return { data: out };
  };

  const missingRequired = (): string | null => {
    for (const k of keys) {
      if (!required.has(k)) continue;
      if (primitiveType(allProps[k]) === "boolean") continue;
      const raw = fields[k];
      if (typeof raw !== "string" || !raw.trim()) return k;
    }
    return null;
  };

  const canSubmit = hasProps ? !missingRequired() : freeText.trim().length > 0;

  const handleSubmit = () => {
    setJsonError(null);
    if (!hasProps) {
      if (!freeText.trim()) return;
      onSubmit({ text: freeText.trim() });
      return;
    }
    const miss = missingRequired();
    if (miss) {
      setJsonError(`"${miss}" is required.`);
      return;
    }
    const { data, err } = buildData();
    if (err) {
      setJsonError(err);
      return;
    }
    if (!data || Object.keys(data).length === 0) {
      setJsonError("Fill in at least one field.");
      return;
    }
    onSubmit({ data });
  };

  const renderField = (k: string) => {
    const p = allProps[k];
    const t = primitiveType(p);
    const label = p.title || k.replace(/_/g, " ");
    const req = required.has(k);
    const hint = p.description;
    const val = fields[k];

    let input: ReactNode;
    if (t === "boolean") {
      input = (
        <input
          type="checkbox"
          className="services-call-checkbox"
          checked={val === true}
          onChange={(e) => setField(k, e.target.checked)}
        />
      );
    } else if (Array.isArray(p.enum) && p.enum.length > 0) {
      input = (
        <select
          className="services-call-input"
          value={typeof val === "string" ? val : ""}
          onChange={(e) => setField(k, e.target.value)}
        >
          <option value="">— select —</option>
          {p.enum.map((opt) => (
            <option key={String(opt)} value={String(opt)}>
              {String(opt)}
            </option>
          ))}
        </select>
      );
    } else if (isScalarArray(p) || isObjectArray(p)) {
      input = (
        <textarea
          className="services-call-textarea"
          value={typeof val === "string" ? val : ""}
          onChange={(e) => setField(k, e.target.value)}
          rows={2}
          placeholder="One per line, or comma-separated"
        />
      );
    } else if (t === "object") {
      input = (
        <textarea
          className="services-call-textarea"
          value={typeof val === "string" ? val : ""}
          onChange={(e) => setField(k, e.target.value)}
          rows={2}
          placeholder='JSON, e.g. {"key": "value"}'
        />
      );
    } else if (t === "number" || t === "integer") {
      input = (
        <input
          type="number"
          className="services-call-input"
          value={typeof val === "string" ? val : ""}
          onChange={(e) => setField(k, e.target.value)}
        />
      );
    } else {
      input = (
        <input
          type="text"
          className="services-call-input"
          value={typeof val === "string" ? val : ""}
          onChange={(e) => setField(k, e.target.value)}
          placeholder={FREE_TEXT_KEYS.has(k.toLowerCase()) ? "Type your request…" : ""}
        />
      );
    }

    return (
      <label className="services-call-field" key={k}>
        <span className="services-call-label">
          {label}
          {req && <span className="services-call-req"> *</span>}
        </span>
        {hint && <span className="services-call-hint">{hint}</span>}
        {input}
      </label>
    );
  };

  return (
    <div className="services-call-form">
      {!hasProps && (
        <label className="services-call-field">
          <span className="services-call-label">Request</span>
          <span className="services-call-hint">
            This agent takes free text — describe what you want.
          </span>
          <textarea
            className="services-call-textarea"
            value={freeText}
            onChange={(e) => setFreeText(e.target.value)}
            rows={3}
            placeholder="e.g. Summarize this paragraph: …"
          />
        </label>
      )}

      {hasProps && shownPrimary.map(renderField)}

      {hasProps && restAdvanced.length > 0 && (
        <details
          className="services-call-advanced"
          open={showAdvanced}
          onToggle={(e) => setShowAdvanced((e.target as HTMLDetailsElement).open)}
        >
          <summary>
            Advanced fields ({restAdvanced.length})
          </summary>
          <div className="services-call-advanced-body">
            {restAdvanced.map(renderField)}
          </div>
        </details>
      )}

      {jsonError && <p className="services-call-err">{jsonError}</p>}

      <button
        type="button"
        className="services-call-submit"
        onClick={handleSubmit}
        disabled={submitting || !canSubmit}
      >
        {submitting ? (
          <>
            <Loader2 size={13} strokeWidth={1.8} className="services-spin" />
            Calling…
          </>
        ) : (
          <>
            Send
            <PhoneCall size={13} strokeWidth={1.8} />
          </>
        )}
      </button>
    </div>
  );
}

function CallResult({ result }: { result: ServiceCallResult }) {
  // The gen-UI renderer inspects the reply shape and picks the right card
  // (status / prose / record / table / list / raw) — replacing the old raw
  // JSON `<pre>` dump and handling the error/partial/empty cases itself.
  return (
    <div className="genui-wrap">
      <GenUiResult result={result} />
    </div>
  );
}
