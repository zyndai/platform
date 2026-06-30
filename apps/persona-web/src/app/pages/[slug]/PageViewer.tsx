"use client";

import { useCallback, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Copy, Check, FileText, Globe } from "lucide-react";

interface PublicPage {
  slug: string;
  url: string;
  title: string;
  format: "html" | "markdown";
  content: string;
  created_at: string | null;
}

function CopyLinkButton({ url }: { url: string }) {
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
    <button
      type="button"
      onClick={handleCopy}
      className="published-page-float-copy"
      aria-label="Copy page link"
    >
      {copied ? <Check size={16} /> : <Copy size={16} />}
      {copied ? "Copied" : "Copy link"}
    </button>
  );
}

function HtmlPage({ page }: { page: PublicPage }) {
  return (
    <>
      <iframe
        title={page.title}
        srcDoc={page.content}
        sandbox=""
        className="published-page-frame-full"
      />
      <CopyLinkButton url={page.url} />
    </>
  );
}

function MarkdownPage({ page }: { page: PublicPage }) {
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
        <div className="published-page-meta-row">
          <div className="published-page-meta">
            <span className="published-page-format md">
              <FileText size={14} />
              Markdown
            </span>
            {formattedDate && (
              <span className="published-page-date">{formattedDate}</span>
            )}
          </div>
          <button
            type="button"
            onClick={handleCopy}
            className="published-page-btn"
            aria-label="Copy page link"
          >
            {copied ? <Check size={16} /> : <Copy size={16} />}
            {copied ? "Copied" : "Copy link"}
          </button>
        </div>
        <h1 className="published-page-title">{page.title}</h1>
      </header>

      <main className="published-page-body">
        <article className="published-page-markdown markdown-content">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{page.content}</ReactMarkdown>
        </article>
      </main>
    </div>
  );
}

export function PageViewer({ page }: { page: PublicPage }) {
  if (page.format === "html") {
    return <HtmlPage page={page} />;
  }
  return <MarkdownPage page={page} />;
}
