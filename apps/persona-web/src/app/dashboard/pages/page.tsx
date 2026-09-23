"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  Globe,
  FileText,
  Copy,
  Check,
  ExternalLink,
  Trash2,
  Plus,
  Pencil,
} from "lucide-react";
import { Button } from "@/components/ui";
import { getSupabase } from "@/lib/supabase";
import PublishHtmlModal from "@/components/chat/PublishHtmlModal";
import type { PublishedPage } from "@/components/chat/PublishedPageCard";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface PageItem {
  slug: string;
  url: string;
  title: string;
  content: string;
  format: "html" | "markdown";
  visibility: string;
  created_at: string | null;
}

export default function DashboardPagesPage() {
  const [pages, setPages] = useState<PageItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingPage, setEditingPage] = useState<PageItem | null>(null);

  const fetchPages = useCallback(async () => {
    try {
      setLoading(true);
      const sb = getSupabase();
      const { data } = await sb.auth.getSession();
      const token = data.session?.access_token;
      const res = await fetch(`${API}/api/pages/`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(await res.text());
      const dataJson = (await res.json()) as { pages: PageItem[] };
      setPages(dataJson.pages || []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load pages");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchPages();
  }, [fetchPages]);

  const deletePage = useCallback(
    async (slug: string) => {
      try {
        const sb = getSupabase();
        const { data } = await sb.auth.getSession();
        const token = data.session?.access_token;
        const res = await fetch(`${API}/api/pages/${slug}`, {
          method: "DELETE",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (!res.ok) throw new Error(await res.text());
        setPages((prev) => prev.filter((p) => p.slug !== slug));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Couldn't delete page");
      }
    },
    [],
  );

  return (
    <div className="dashboard-pages">
      <header className="dashboard-pages-header">
        <div>
          <h1>Your pages</h1>
          <p>HTML and Markdown pages you&apos;ve published from chat.</p>
        </div>
        <Link href="/dashboard/chat">
          <Button size="sm" leftIcon={<Plus size={16} />}>
            Create from chat
          </Button>
        </Link>
      </header>

      {error && <div className="dashboard-pages-error">{error}</div>}

      {loading ? (
        <div className="dashboard-pages-empty">Loading…</div>
      ) : pages.length === 0 ? (
        <div className="dashboard-pages-empty">
          <Globe size={40} strokeWidth={1.2} />
          <h2>No pages yet</h2>
          <p>
            Ask your agent to publish something, e.g.{" "}
            <em>&quot;Publish this as an HTML page&quot;</em>.
          </p>
        </div>
      ) : (
        <ul className="dashboard-pages-list">
          {pages.map((page) => (
            <PageRow
              key={page.slug}
              page={page}
              onDelete={deletePage}
              onEdit={() => setEditingPage(page)}
            />
          ))}
        </ul>
      )}

      {editingPage && (
        <PublishHtmlModal
          page={editingPage}
          onClose={() => setEditingPage(null)}
          onSaved={(saved: PublishedPage) => {
            setPages((prev) =>
              prev.map((p) =>
                p.slug === editingPage.slug
                  ? { ...p, title: saved.title, visibility: saved.visibility || p.visibility }
                  : p,
              ),
            );
          }}
        />
      )}
    </div>
  );
}

function PageRow({
  page,
  onDelete,
  onEdit,
}: {
  page: PageItem;
  onDelete: (slug: string) => void;
  onEdit: () => void;
}) {
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

  const isHtml = page.format === "html";
  const created = page.created_at
    ? new Date(page.created_at).toLocaleDateString()
    : null;

  return (
    <li className="dashboard-pages-item">
      <div className="dashboard-pages-info">
        <span className={`dashboard-pages-format ${isHtml ? "html" : "md"}`}>
          {isHtml ? <Globe size={13} /> : <FileText size={13} />}
          {isHtml ? "HTML" : "Markdown"}
        </span>
        <h3>{page.title || "Untitled page"}</h3>
        <div className="dashboard-pages-meta">
          <span className="dashboard-pages-visibility">{page.visibility}</span>
          {created && <span>{created}</span>}
        </div>
      </div>
      <div className="dashboard-pages-actions">
        <button type="button" className="page-action-btn" onClick={handleCopy}>
          {copied ? <Check size={15} /> : <Copy size={15} />}
          {copied ? "Copied" : "Copy"}
        </button>
        <a
          href={page.url}
          target="_blank"
          rel="noopener noreferrer"
          className="page-action-btn"
        >
          <ExternalLink size={15} />
          Open
        </a>
        <button type="button" className="page-action-btn" onClick={onEdit}>
          <Pencil size={15} />
          Edit
        </button>
        <button
          type="button"
          className="page-action-btn danger"
          onClick={() => onDelete(page.slug)}
          aria-label={`Delete ${page.title || "Untitled page"}`}
        >
          <Trash2 size={15} />
        </button>
      </div>
    </li>
  );
}
