"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, X } from "lucide-react";
import { Button } from "@/components/ui";
import { apiPatch, apiPost } from "@/lib/api";
import PublishedPageCard, { type PublishedPage } from "./PublishedPageCard";

type Visibility = "unlisted" | "public" | "private";

/** Pass an existing page to open the modal in edit mode, pre-filled. */
export interface EditablePage {
  slug: string;
  title: string;
  content: string;
  visibility: string;
}

interface PublishHtmlModalProps {
  onClose: () => void;
  /** Called after a successful publish/save with the resulting page. */
  onSaved?: (page: PublishedPage) => void;
  page?: EditablePage | null;
}

function isVisibility(v: string): v is Visibility {
  return v === "unlisted" || v === "public" || v === "private";
}

/**
 * Paste-and-publish (or edit) a full HTML page via POST/PATCH /api/pages/ —
 * bypassing the chat message's MAX_CHARS cap entirely, since this never
 * travels through the chat textarea or the orchestrator.
 */
export default function PublishHtmlModal({ onClose, onSaved, page }: PublishHtmlModalProps) {
  const isEdit = !!page;
  const [title, setTitle] = useState(page?.title ?? "");
  const [content, setContent] = useState(page?.content ?? "");
  const [visibility, setVisibility] = useState<Visibility>(
    page && isVisibility(page.visibility) ? page.visibility : "unlisted",
  );
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [published, setPublished] = useState<PublishedPage | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !publishing) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, publishing]);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  const handleSubmit = async () => {
    const html = content.trim();
    if (!html || publishing) return;
    setPublishing(true);
    setError(null);
    try {
      const result = isEdit
        ? await apiPatch<PublishedPage>(`/api/pages/${page!.slug}`, {
            content: html,
            title,
            visibility,
          })
        : await apiPost<PublishedPage>("/api/pages/", {
            content: html,
            title,
            format: "html",
            visibility,
          });
      setPublished(result);
      onSaved?.(result);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : `Couldn't ${isEdit ? "save" : "publish"}. Try again.`,
      );
    } finally {
      setPublishing(false);
    }
  };

  return (
    <div
      className="intro-modal-scrim"
      onClick={() => !publishing && onClose()}
      role="dialog"
      aria-modal="true"
    >
      <div className="intro-modal" onClick={(e) => e.stopPropagation()}>
        <div className="intro-modal-header">
          <div className="recipient-info">
            <div className="name">{isEdit ? "Edit page" : "Publish HTML"}</div>
            <div className="title body-s">
              {isEdit
                ? "Update the content, title, or visibility of this page."
                : "Paste a full page — there's no length limit here, unlike chat."}
            </div>
          </div>
          <button
            type="button"
            className="close-btn"
            onClick={onClose}
            disabled={publishing}
            aria-label="Close"
          >
            <X size={18} strokeWidth={1.5} />
          </button>
        </div>

        <div className="intro-modal-body">
          {error && (
            <div className="banner banner-danger" role="alert" style={{ marginBottom: 12 }}>
              <span className="banner-msg">⚠ {error}</span>
            </div>
          )}

          {published ? (
            <PublishedPageCard result={published} />
          ) : (
            <>
              <input
                type="text"
                className="intro-draft publish-title-input"
                placeholder="Page title (optional)"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                disabled={publishing}
              />
              <textarea
                ref={textareaRef}
                className="intro-draft publish-html-textarea"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                disabled={publishing}
                rows={16}
                placeholder="<html>...</html>"
                aria-label="HTML content to publish"
              />
              <div className="publish-visibility-row">
                <label htmlFor="publish-visibility">Visibility</label>
                <div className="publish-select-wrap">
                  <select
                    id="publish-visibility"
                    className="publish-select"
                    value={visibility}
                    onChange={(e) => setVisibility(e.target.value as Visibility)}
                    disabled={publishing}
                  >
                    <option value="unlisted">Unlisted — anyone with the link</option>
                    <option value="public">Public</option>
                    <option value="private">Private — only me</option>
                  </select>
                  <ChevronDown size={15} className="publish-select-chevron" aria-hidden="true" />
                </div>
              </div>
            </>
          )}
        </div>

        <div className="intro-modal-footer">
          <Button variant="tertiary" onClick={onClose} disabled={publishing}>
            {published ? "Done" : "Cancel"}
          </Button>
          {!published && (
            <Button onClick={handleSubmit} disabled={publishing || !content.trim()}>
              {publishing
                ? isEdit ? "Saving…" : "Publishing…"
                : isEdit ? "Save changes" : "Publish"}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
