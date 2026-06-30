"use client";

import { useCallback, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ExternalLink, Copy, Check, FileText, Globe } from "lucide-react";

interface PublicPage {
  slug: string;
  url: string;
  title: string;
  format: "html" | "markdown";
  content: string;
  created_at: string | null;
}

export function PageViewer({ page }: { page: PublicPage }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(page.url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  }, [page.url]);

  const formattedDate = page.created_at
    ? new Date(page.created_at).toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      })
    : null;

  return (
    <div className="published-page">
      <header className="published-page-header">
        <div className="published-page-meta">
          <span className="published-page-format">
            {page.format === "html" ? <Globe size={14} /> : <FileText size={14} />}
            {page.format === "html" ? "HTML" : "Markdown"}
          </span>
          {formattedDate && <span className="published-page-date">{formattedDate}</span>}
        </div>
        <h1 className="published-page-title">{page.title}</h1>
        <div className="published-page-actions">
          <button
            type="button"
            onClick={handleCopy}
            className="published-page-btn"
            aria-label="Copy page link"
          >
            {copied ? <Check size={16} /> : <Copy size={16} />}
            {copied ? "Copied" : "Copy link"}
          </button>
          <a
            href={page.url}
            target="_blank"
            rel="noopener noreferrer"
            className="published-page-btn primary"
          >
            <ExternalLink size={16} />
            Open
          </a>
        </div>
      </header>

      <div className="published-page-body">
        {page.format === "html" ? (
          <iframe
            title={page.title}
            srcDoc={page.content}
            sandbox=""
            className="published-page-frame"
          />
        ) : (
          <article className="published-page-markdown markdown-content">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{page.content}</ReactMarkdown>
          </article>
        )}
      </div>
    </div>
  );
}
