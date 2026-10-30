"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { CARDS_API } from "@/lib/cards";
import type { AgentProfileCard, BuildStage, OnboardStatus, ScrapeWarning, SourceStatus } from "@/lib/cards";
import { appendAttrToForm } from "@/lib/attr";
import { track } from "@/lib/track";
import { sameUrls } from "./model";

/** How long after the last pasted link or dropped résumé the build starts. */
const START_DELAY_MS = 1200;
const POLL_MS = 1000;
/** Matches the API's own pipeline limit, with room for the last poll. */
const GIVE_UP_MS = 210_000;

export interface BuildState {
  status: "idle" | "running" | "ready" | "error";
  jobId: string | null;
  stage: BuildStage;
  sources: SourceStatus[];
  warnings: ScrapeWarning[];
  /** The newest finished draft. Kept while a newer build runs, so the preview never blanks. */
  card: AgentProfileCard | null;
  /** Which kind of professional the synthesis decided this is: picks the chip vocabulary. "" until a draft exists. */
  persona: string;
  error: string | null;
  /** What the newest build was started from. */
  inputs: { urls: string[]; resume: File | null };
}

const IDLE: BuildState = {
  status: "idle", jobId: null, stage: "reading", sources: [], warnings: [], card: null, persona: "", error: null,
  inputs: { urls: [], resume: null },
};

function stopJob(id: string): void {
  void fetch(`${CARDS_API}/onboard/${id}/cancel`, { method: "POST", keepalive: true }).catch(() => { /* already finished or gone */ });
}

/**
 * Builds the card from the links and résumé as they are added: no button for
 * the first draft. Until it is ready every change restarts the build (after a
 * short pause, so pasting three links is one build) and stops the one it
 * replaces. Once a draft exists a change only marks it `stale`, and `retry`
 * rebuilds: each build re-reads every source and pays for a model call, and
 * the person may be adding a link they are not finished with.
 */
export function useBuild({ urls, resume, enabled }: { urls: string[]; resume: File | null; enabled: boolean }) {
  const [build, setBuild] = useState<BuildState>(IDLE);
  const generation = useRef(0);
  const job = useRef<{ id: string; timer: ReturnType<typeof setInterval> } | null>(null);
  const latest = useRef({ urls, resume });
  useEffect(() => { latest.current = { urls, resume }; });

  /** Stop polling and tell the API to stop paying for the build; any pending start is void. */
  const halt = useCallback(() => {
    generation.current += 1;
    if (job.current) {
      clearInterval(job.current.timer);
      stopJob(job.current.id);
      job.current = null;
    }
  }, []);

  const start = useCallback(async (sourceUrls: string[], file: File | null) => {
    halt();
    if (sourceUrls.length === 0 && !file) {
      setBuild(IDLE);
      return;
    }
    const mine = generation.current;
    setBuild((s) => ({
      ...s, status: "running", stage: "reading", jobId: null, sources: [], warnings: [], error: null,
      inputs: { urls: sourceUrls, resume: file },
    }));
    track("create_build_started", { sources: sourceUrls.length, resume: !!file });

    const fail = (error: string) => {
      if (generation.current !== mine) return;
      if (job.current) { clearInterval(job.current.timer); job.current = null; }
      setBuild((s) => ({ ...s, status: "error", error }));
    };

    let id: string;
    try {
      const form = new FormData();
      sourceUrls.forEach((u) => form.append("url", u));
      if (file) form.append("resume", file);
      appendAttrToForm(form);
      const res = await fetch(`${CARDS_API}/onboard/start`, { method: "POST", body: form, signal: AbortSignal.timeout(15_000) });
      if (res.status === 429) throw new Error("Too many card builds from this network. Wait a few minutes, then retry.");
      if (!res.ok) throw new Error((await res.text()) || `Status ${res.status}`);
      id = (await res.json()).job_id as string;
    } catch (err) {
      fail(err instanceof Error ? err.message : "Failed to start");
      return;
    }
    if (generation.current !== mine) { stopJob(id); return; }

    const deadline = Date.now() + GIVE_UP_MS;
    let busy = false;
    const poll = async () => {
      if (generation.current !== mine || busy) return;
      if (Date.now() >= deadline) {
        fail("Building your card took too long. Your links are kept; retry or use fewer sources.");
        return;
      }
      busy = true;
      try {
        const res = await fetch(`${CARDS_API}/onboard/${id}`, { signal: AbortSignal.timeout(10_000) });
        if (generation.current !== mine) return;
        if (res.status === 404 || res.status === 410) {
          fail("This build expired or the server restarted. Your inputs are kept; please retry.");
          return;
        }
        if (!res.ok) return;
        const status: OnboardStatus = await res.json();
        if (generation.current !== mine) return;
        if (status.status === "error") {
          fail(status.error || "Unknown error");
          return;
        }
        const ready = status.status === "ready" && status.card;
        if (ready) {
          if (job.current) { clearInterval(job.current.timer); job.current = null; }
          track("create_draft_ready", { persona: status.persona ?? "" });
        }
        setBuild((s) => ({
          ...s,
          status: ready ? "ready" : "running",
          jobId: id,
          stage: ready ? "ready" : status.stage ?? "reading",
          sources: status.sources ?? [],
          warnings: status.url_warnings ?? [],
          card: ready ? status.card : s.card,
          persona: ready ? status.persona ?? "" : s.persona,
        }));
      } catch { /* transient: the deadline still bounds the retries */ }
      finally { busy = false; }
    };
    job.current = { id, timer: setInterval(() => void poll(), POLL_MS) };
    void poll();
  }, [halt]);

  const hasDraft = build.card !== null;
  useEffect(() => {
    if (!enabled || hasDraft) return;
    const t = setTimeout(() => void start(urls, resume), urls.length || resume ? START_DELAY_MS : 0);
    return () => clearTimeout(t);
  }, [urls, resume, enabled, hasDraft, start]);

  // Leaving the page, or finishing (published), ends any build still running.
  useEffect(() => { if (!enabled) halt(); }, [enabled, halt]);
  useEffect(() => halt, [halt]);

  const retry = useCallback(() => void start(latest.current.urls, latest.current.resume), [start]);

  /** The draft was built from other sources than the ones listed now. */
  const stale = build.status === "ready" && hasDraft
    && (!sameUrls(urls, build.inputs.urls) || resume !== build.inputs.resume);

  return { build, retry, stale };
}
