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
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ExternalLink, Search, FileCode, Tag } from "lucide-react";
import type { ServicesPanelPayload } from "./types";
import type {
  ServiceCardPayload,
  ServiceSearchResult,
} from "@/lib/services-commands";

interface ServicesPanelProps {
  payload: ServicesPanelPayload;
  /** Called when the user clicks "View card" on a search result.
   *  The parent runs the fetch and appends a new card-payload message. */
  onCardLookup?: (entityId: string) => void;
}

export default function ServicesPanel({ payload, onCardLookup }: ServicesPanelProps) {
  if (payload.loading) {
    return (
      <div className="services-panel services-panel-loading">
        <Search size={14} strokeWidth={1.6} />
        <span>
          {payload.kind === "search"
            ? `Searching Zynd services for "${payload.query}"…`
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
            />
          ))}
        </ul>
      </div>
    );
  }

  if (payload.kind === "card") {
    const c = payload.card;
    if (!c) return null;
    return <ServiceCardDetail card={c} />;
  }

  return null;
}

function ServiceResultRow({
  result,
  onView,
}: {
  result: ServiceSearchResult;
  onView?: () => void;
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
        <div className="service-result-id" title={result.entity_id}>
          {result.entity_id}
        </div>
      </div>
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
    </li>
  );
}

function ServiceCardDetail({ card }: { card: ServiceCardPayload }) {
  const [schemaOpen, setSchemaOpen] = useState(false);

  if (card.status === "not_found") {
    return (
      <div className="services-panel services-panel-empty">
        <p>
          No service with id <code>{card.entity_id}</code> is registered.
        </p>
      </div>
    );
  }
  if (card.status === "unreachable") {
    return (
      <div className="services-panel services-panel-empty">
        <p>
          <strong>{card.entity_id}</strong> is registered but its deployment is
          unreachable.
        </p>
        {card.hint && <p className="services-panel-hint">{card.hint}</p>}
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

  const schema = card.input_schema as
    | { properties?: Record<string, unknown> }
    | undefined;
  const fieldKeys = schema?.properties ? Object.keys(schema.properties) : [];

  return (
    <div className="services-panel services-card-detail">
      <div className="services-card-head">
        <div>
          <div className="services-card-name">{card.name || "Service"}</div>
          <div className="services-card-id">{card.entity_id}</div>
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

      {card.url && (
        <a
          href={card.url}
          target="_blank"
          rel="noopener noreferrer"
          className="services-card-url"
        >
          <ExternalLink size={12} strokeWidth={1.8} />
          {card.url}
        </a>
      )}

      {fieldKeys.length > 0 && (
        <div className="services-card-fields">
          <div className="services-card-section">Input fields</div>
          <div className="services-card-field-chips">
            {fieldKeys.map((k) => (
              <span key={k} className="services-card-chip">
                {k}
              </span>
            ))}
          </div>
        </div>
      )}

      {schema && (
        <details
          className="services-card-schema"
          open={schemaOpen}
          onToggle={(e) => setSchemaOpen((e.target as HTMLDetailsElement).open)}
        >
          <summary>Full input schema</summary>
          <pre className="services-card-schema-pre">
            {JSON.stringify(card.input_schema, null, 2)}
          </pre>
        </details>
      )}

      {card.hint && <p className="services-panel-hint">{card.hint}</p>}
    </div>
  );
}
