"use client";

import { useState, useCallback } from "react";
import {
  ExternalLink,
  Copy,
  Check,
  Globe,
  FileText,
  Link as LinkIcon,
} from "lucide-react";

export interface PublishedPage {
  slug: string;
  url: string;
  title: string;
  format: "html" | "markdown";
  visibility?: string;
  created_at?: string | null;
}

export function isPublishedPageResult(result: unknown): result is PublishedPage {
  if (!result || typeof result !== "object") return false;
  const r = result as Record<string, unknown>;
  return (
    typeof r.slug === "string" &&
    typeof r.url === "string" &&
    (r.format === "html" || r.format === "markdown")
  );
}

function CopyOpenButtons({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  }, [url]);

  return (
    <div className="published-page-card-actions">
      <button type="button" className="page-card-btn" onClick={handleCopy}>
        {copied ? <Check size={14} /> : <Copy size={14} />}
        {copied ? "Copied" : "Copy link"}
      </button>
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="page-card-btn primary"
      >
        <ExternalLink size={14} />
        Open page
      </a>
    </div>
  );
}

export default function PublishedPageCard({ result }: { result: PublishedPage }) {
  const isHtml = result.format === "html";

  return (
    <div className="published-page-card">
      <div className="page-card-head">
        <span className={`page-card-format ${isHtml ? "html" : "md"}`}>
          {isHtml ? <Globe size={14} /> : <FileText size={14} />}
          {isHtml ? "HTML page" : "Markdown page"}
        </span>
      </div>
      <div className="page-card-title">{result.title || "Untitled page"}</div>
      <div className="page-card-url">
        <LinkIcon size={12} />
        <span>{result.url}</span>
      </div>
      <CopyOpenButtons url={result.url} />
    </div>
  );
}

export function PageListCard({
  pages,
}: {
  pages: PublishedPage[];
}) {
  if (pages.length === 0) {
    return (
      <div className="published-page-card empty">
        You haven&apos;t published any pages yet.
      </div>
    );
  }

  return (
    <div className="published-page-card list">
      <div className="page-card-head">
        <span className="page-card-format">
          <Globe size={14} />
          Your pages
        </span>
      </div>
      <ul className="page-card-list">
        {pages.map((page) => (
          <li key={page.slug} className="page-card-list-item">
            <a
              href={page.url}
              target="_blank"
              rel="noopener noreferrer"
              className="page-card-list-link"
              title={page.title}
            >
              <span className="page-card-list-title">
                {page.title || "Untitled page"}
              </span>
              <span className="page-card-list-format">{page.format}</span>
            </a>
            <div className="page-card-list-actions">
              <CopyButton value={page.url} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  }, [value]);

  return (
    <button type="button" className="page-card-btn" onClick={handleCopy}>
      {copied ? <Check size={14} /> : <Copy size={14} />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}
