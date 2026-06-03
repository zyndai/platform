"use client";

/**
 * Generative-UI renderer for service / agent call results.
 *
 * Given a ServiceCallResult it inspects the *shape* of the reply and picks the
 * card that fits: a status notice, a markdown prose block, a key/value record,
 * a table, a list, or a raw-JSON fallback. Every card exposes a collapsible
 * "view raw" disclosure and a count badge ("5 rows", "142 lines", …).
 *
 * `LongResponseCard` is the sibling for the model's *own* long prose: it pins
 * a fixed-height, internally-scrolling card so a big streaming answer stops
 * growing the chat thread, with a live line counter in the footer.
 */

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  AlertTriangle,
  Clock,
  CheckCircle2,
  Copy,
  Check,
  ChevronDown,
  Braces,
  FileText,
} from "lucide-react";
import type { ServiceCallResult } from "@/lib/services-commands";

// ── value helpers ───────────────────────────────────────────────────────
type Scalar = string | number | boolean | null | undefined;

function isScalar(x: unknown): x is Scalar {
  return x == null || ["string", "number", "boolean"].includes(typeof x);
}
function isPlainObject(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}
function humanizeKey(k: string): string {
  const s = k
    .replace(/[_-]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}
function formatScalar(x: Scalar): string {
  if (x === null || x === undefined || x === "") return "—";
  if (typeof x === "boolean") return x ? "Yes" : "No";
  return String(x);
}
function lineCount(text: string): number {
  return text ? text.split("\n").length : 0;
}

/** Threshold past which the model's own prose flips into a contained card. */
export function isLongResponse(text: string): boolean {
  if (!text) return false;
  return text.split("\n").length > 24 || text.length > 1400;
}

// ── shared affordances ──────────────────────────────────────────────────
function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="genui-copy"
      onClick={() => {
        navigator.clipboard
          ?.writeText(value)
          .then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          })
          .catch(() => {});
      }}
    >
      {copied ? <Check size={12} strokeWidth={2} /> : <Copy size={12} strokeWidth={1.8} />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function RawDisclosure({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === "") return null;
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <details className="genui-raw">
      <summary>
        <Braces size={12} strokeWidth={1.8} /> View raw
      </summary>
      <div className="genui-raw-body">
        <div className="genui-raw-actions">
          <CopyButton value={text} />
        </div>
        <pre className="services-call-result-pre">{text}</pre>
      </div>
    </details>
  );
}

/** Height clamp with a "Show more" toggle for tall bodies. */
function Clamp({ children, maxPx = 340 }: { children: ReactNode; maxPx?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (el) setOverflows(el.scrollHeight > maxPx + 8);
  }, [maxPx]);
  return (
    <div className="genui-clamp">
      <div
        ref={ref}
        className={`genui-clamp-body${expanded ? " is-expanded" : ""}${
          overflows && !expanded ? " is-faded" : ""
        }`}
        style={!expanded ? { maxHeight: maxPx } : undefined}
      >
        {children}
      </div>
      {overflows && (
        <button
          type="button"
          className="genui-clamp-toggle"
          onClick={() => setExpanded((v) => !v)}
        >
          <ChevronDown size={13} strokeWidth={2} className={expanded ? "is-up" : ""} />
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}

function Shell({
  title,
  statusWord,
  tone = "default",
  count,
  rawValue,
  children,
}: {
  title?: string;
  statusWord: string;
  tone?: "error" | "pending" | "default";
  count?: string;
  rawValue?: unknown;
  children: ReactNode;
}) {
  const Icon = tone === "error" ? AlertTriangle : tone === "pending" ? Clock : CheckCircle2;
  return (
    <div className={`genui-card${tone === "error" ? " is-error" : ""}`}>
      <div className="genui-head">
        <Icon size={14} strokeWidth={1.8} className="genui-head-icon" />
        <span className="genui-head-title">{title || "Result"}</span>
        <span className="genui-head-status">{statusWord}</span>
      </div>
      <div className="genui-body">{children}</div>
      {count && (
        <div className="genui-foot">
          <span className="genui-count">{count}</span>
        </div>
      )}
      <RawDisclosure value={rawValue} />
    </div>
  );
}

// ── shape → descriptor ──────────────────────────────────────────────────
type GenUiNode =
  | { kind: "status"; tone: "error" | "pending" | "empty" | "default"; statusWord: string; message: string }
  | { kind: "prose"; statusWord: string; markdown: string }
  | { kind: "table"; statusWord: string; rows: Record<string, unknown>[] }
  | { kind: "list"; statusWord: string; items: unknown[] }
  | { kind: "record"; statusWord: string; obj: Record<string, unknown> }
  | { kind: "raw"; statusWord: string; value: unknown };

function statusWordFor(result: ServiceCallResult): string {
  switch (result.status) {
    case "error":
    case "remote_failed":
    case "bad_request":
      return "Call failed";
    case "auth_required":
      return "Auth required";
    case "rejected":
      return "Rejected";
    case "partial":
    case "working":
      return result.task_state ? `Working (${result.task_state})` : "Working…";
    case "needs_input":
      return "Needs input";
    default:
      return "Reply";
  }
}

export function pickRenderer(result: ServiceCallResult): GenUiNode {
  const statusWord = statusWordFor(result);
  const st = result.status as string;

  if (st === "error" || st === "auth_required" || st === "remote_failed" || st === "bad_request" || st === "rejected") {
    return {
      kind: "status",
      tone: "error",
      statusWord,
      message:
        result.error_message ||
        result.error ||
        (st === "auth_required"
          ? "This agent needs you to authenticate first."
          : "The service returned an error."),
    };
  }
  if (st === "partial" || st === "working" || st === "needs_input") {
    return {
      kind: "status",
      tone: "pending",
      statusWord,
      message:
        result.reply_text?.trim() ||
        (st === "needs_input"
          ? "The service is waiting for more information."
          : "The service is still working on this…"),
    };
  }

  const so = result.structured_output;
  const hasSo =
    so !== null && so !== undefined && !(typeof so === "string" && so.trim() === "");

  if (!hasSo) {
    if (result.reply_text && result.reply_text.trim())
      return { kind: "prose", statusWord, markdown: result.reply_text };
    return {
      kind: "status",
      tone: "empty",
      statusWord,
      message: "The service ran but returned no readable output.",
    };
  }

  if (typeof so === "string") return { kind: "prose", statusWord, markdown: so };

  return classifyValue(so, statusWord);
}

function classifyValue(v: unknown, statusWord: string): GenUiNode {
  if (Array.isArray(v)) {
    if (v.length === 0)
      return { kind: "status", tone: "empty", statusWord, message: "Empty list." };
    if (v.every(isPlainObject) && isUniformScalarTable(v as Record<string, unknown>[]))
      return { kind: "table", statusWord, rows: v as Record<string, unknown>[] };
    return { kind: "list", statusWord, items: v };
  }
  if (isPlainObject(v)) {
    const entries = Object.entries(v);
    if (
      entries.length <= 3 &&
      entries.every(([, x]) => isScalar(x)) &&
      ("status" in v || "ok" in v || "message" in v || "error" in v)
    ) {
      const isErr = (!!v.error) || v.ok === false || v.status === "error";
      const msg =
        formatScalar(v.message as Scalar) !== "—"
          ? String(v.message)
          : formatScalar(v.error as Scalar) !== "—"
            ? String(v.error)
            : `Status: ${formatScalar((v.status ?? v.ok) as Scalar)}`;
      return { kind: "status", tone: isErr ? "error" : "default", statusWord, message: msg };
    }
    const scalarCount = entries.filter(([, x]) => isScalar(x)).length;
    const scalarRatio = entries.length ? scalarCount / entries.length : 0;
    if (scalarRatio >= 0.6) return { kind: "record", statusWord, obj: v };
    return { kind: "raw", statusWord, value: v };
  }
  return { kind: "prose", statusWord, markdown: String(v) };
}

function isUniformScalarTable(rows: Record<string, unknown>[]): boolean {
  if (rows.length < 2) return false;
  const union = new Set<string>();
  rows.forEach((r) => Object.keys(r).forEach((k) => union.add(k)));
  if (union.size === 0 || union.size > 8) return false;
  const shared = [...union].filter((k) => rows.every((r) => k in r));
  if (shared.length === 0) return false;
  let scalarCells = 0;
  let totalCells = 0;
  for (const r of rows)
    for (const k of union) {
      totalCells++;
      if (k in r && isScalar(r[k])) scalarCells++;
    }
  return totalCells > 0 && scalarCells / totalCells >= 0.6;
}

// ── recursive value renderers ───────────────────────────────────────────
function renderValue(v: unknown, depth: number): ReactNode {
  if (isScalar(v)) return formatScalar(v as Scalar);
  if (depth >= 2) return <code className="genui-inline-json">{JSON.stringify(v)}</code>;
  if (Array.isArray(v)) return <ListView items={v} depth={depth + 1} nested />;
  if (isPlainObject(v)) return <RecordView obj={v} depth={depth + 1} />;
  return String(v);
}

function RecordView({ obj, depth = 0 }: { obj: Record<string, unknown>; depth?: number }) {
  return (
    <div className="genui-record">
      {Object.entries(obj).map(([k, v]) => (
        <div className="genui-row" key={k}>
          <span className="genui-row-label">{humanizeKey(k)}</span>
          <span className="genui-row-value">{renderValue(v, depth)}</span>
        </div>
      ))}
    </div>
  );
}

function ListView({
  items,
  depth = 0,
  nested = false,
}: {
  items: unknown[];
  depth?: number;
  nested?: boolean;
}) {
  return (
    <ul className={`genui-list${nested ? " is-nested" : ""}`}>
      {items.map((it, i) => (
        <li key={i}>{renderValue(it, depth)}</li>
      ))}
    </ul>
  );
}

function tableColumns(rows: Record<string, unknown>[]): string[] {
  const cols: string[] = [];
  const seen = new Set<string>();
  for (const r of rows)
    for (const k of Object.keys(r))
      if (!seen.has(k)) {
        seen.add(k);
        cols.push(k);
      }
  return cols.slice(0, 8);
}

function TableView({ rows, cols }: { rows: Record<string, unknown>[]; cols: string[] }) {
  const [showAll, setShowAll] = useState(false);
  const LIMIT = 8;
  const visible = showAll ? rows : rows.slice(0, LIMIT);
  const cell = (v: unknown) => (isScalar(v) ? formatScalar(v as Scalar) : JSON.stringify(v));
  return (
    <div className="genui-table-wrap">
      <table className="genui-table">
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c}>{humanizeKey(c)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visible.map((r, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c}>{cell(r[c])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > LIMIT && (
        <button
          type="button"
          className="genui-clamp-toggle"
          onClick={() => setShowAll((v) => !v)}
        >
          {showAll ? "Show fewer rows" : `Show ${rows.length - LIMIT} more rows`}
        </button>
      )}
    </div>
  );
}

// ── public renderer ─────────────────────────────────────────────────────
export default function GenUiResult({
  result,
  title,
}: {
  result: ServiceCallResult;
  title?: string;
}) {
  const node = pickRenderer(result);
  const raw =
    result.structured_output ?? (result.reply_text || null) ?? null;
  const cardTitle = title || result.entity_id || "Result";

  switch (node.kind) {
    case "status":
      return (
        <Shell
          title={cardTitle}
          statusWord={node.statusWord}
          tone={node.tone === "empty" ? "default" : node.tone}
          rawValue={node.tone === "empty" ? null : raw}
        >
          <div className={`genui-status is-${node.tone}`}>
            <p>{node.message}</p>
          </div>
        </Shell>
      );

    case "prose":
      return (
        <Shell
          title={cardTitle}
          statusWord={node.statusWord}
          count={`${lineCount(node.markdown)} lines`}
          rawValue={raw}
        >
          <Clamp>
            <div className="markdown-content">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{node.markdown}</ReactMarkdown>
            </div>
          </Clamp>
        </Shell>
      );

    case "record": {
      const n = Object.keys(node.obj).length;
      return (
        <Shell
          title={cardTitle}
          statusWord={node.statusWord}
          count={`${n} field${n === 1 ? "" : "s"}`}
          rawValue={raw}
        >
          <Clamp>
            <RecordView obj={node.obj} />
          </Clamp>
        </Shell>
      );
    }

    case "table": {
      const cols = tableColumns(node.rows);
      return (
        <Shell
          title={cardTitle}
          statusWord={node.statusWord}
          count={`${node.rows.length} rows × ${cols.length} cols`}
          rawValue={raw}
        >
          <TableView rows={node.rows} cols={cols} />
        </Shell>
      );
    }

    case "list":
      return (
        <Shell
          title={cardTitle}
          statusWord={node.statusWord}
          count={`${node.items.length} item${node.items.length === 1 ? "" : "s"}`}
          rawValue={raw}
        >
          <Clamp>
            <ListView items={node.items} />
          </Clamp>
        </Shell>
      );

    case "raw":
    default:
      return (
        <Shell title={cardTitle} statusWord={node.statusWord} rawValue={null}>
          <div className="genui-raw-actions">
            <CopyButton value={JSON.stringify(node.value, null, 2)} />
          </div>
          <Clamp>
            <pre className="services-call-result-pre">
              {JSON.stringify(node.value, null, 2)}
            </pre>
          </Clamp>
        </Shell>
      );
  }
}

/**
 * Wraps the model's own long prose in a fixed-height, internally-scrolling
 * card so a big streaming answer doesn't grow the chat thread. The body
 * auto-pins to the bottom while streaming; the footer shows a live line count.
 */
export function LongResponseCard({
  markdown,
  streaming,
}: {
  markdown: string;
  streaming?: boolean;
}) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (streaming && !expanded && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [markdown, streaming, expanded]);
  const lines = lineCount(markdown);
  return (
    <div className="genui-card genui-stream">
      <div className="genui-head">
        <FileText size={14} strokeWidth={1.8} className="genui-head-icon" />
        <span className="genui-head-title">Response</span>
        <span className="genui-head-status">{streaming ? "Generating…" : "Done"}</span>
      </div>
      <div
        ref={bodyRef}
        className={`genui-body genui-stream-body${expanded ? " is-expanded" : ""}`}
      >
        <div className="markdown-content">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
        </div>
      </div>
      <div className="genui-foot">
        <span className="genui-count">
          {lines} lines{streaming ? " · generating…" : ""}
        </span>
        <span className="genui-foot-spacer" />
        <button
          type="button"
          className="genui-clamp-toggle"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "Collapse" : "Expand"}
        </button>
      </div>
      <RawDisclosure value={markdown} />
    </div>
  );
}
