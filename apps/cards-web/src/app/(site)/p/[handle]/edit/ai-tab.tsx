"use client";

import { useEffect, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { CARDS_API } from "@/lib/cards";
import { memoryFactKey, ownerFactCount, ownerFactGroups, type OwnerFactDetail } from "@/lib/memory-facts";
import { fetchOwnerCardFacts, type MemorySnapshot } from "@/lib/mcp-connector";
import { OwnerMemoryList } from "@/components/memory/OwnerMemoryList";
import { MemoryProviderOnboard } from "@/components/memory/MemoryProviderOnboard";
import { McpConnectPanel } from "@/components/mcp/McpConnectPanel";
import { SuggestedFactsReview } from "@/components/mcp/SuggestedFactsReview";
import { Card, type ShowToast } from "./edit-ui";

type Facts = Array<Record<string, unknown>>;

function formatAgo(ms: number | null, now: number): string {
  if (!ms) return "";
  const s = Math.max(0, Math.floor((now - ms) / 1000));
  if (s < 10) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  return `${Math.floor(m / 60)}h ago`;
}

export function AiTab({ handle, token, firstName, initialFacts, onFactsChange, onReviewCount, showToast }: {
  handle: string;
  token: string;
  firstName: string;
  initialFacts: Facts;
  onFactsChange: (facts: Facts) => void;
  onReviewCount: (n: number) => void;
  showToast: ShowToast;
}) {
  const [facts, setFacts] = useState<Facts>(initialFacts);
  const [syncing, setSyncing] = useState(false);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [lastSync, setLastSync] = useState<number | null>(null);
  const [now, setNow] = useState<number>(() => Date.now());
  // Owner-only origin and evidence for each public fact, keyed by memoryFactKey. Optional:
  // if it fails to load the list still renders, from the snapshot's own provenance.
  const [details, setDetails] = useState<Record<string, OwnerFactDetail>>({});

  useEffect(() => {
    if (!token || facts.length === 0) return;
    let cancelled = false;
    fetchOwnerCardFacts(token)
      .then((rows) => {
        if (cancelled) return;
        const next: Record<string, OwnerFactDetail> = {};
        for (const f of rows) {
          if (f.predicate && f.object) {
            next[memoryFactKey(f.predicate, f.object)] = { provenance: f.provenance, evidence: f.evidence };
          }
        }
        setDetails(next);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [token, facts]);

  useEffect(() => {
    if (connected !== true) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [connected]);

  function applyFacts(next: Facts) {
    setFacts(next);
    onFactsChange(next);
    setConnected(true);
    setLastSync(Date.now());
  }

  async function sync() {
    setSyncing(true);
    try {
      const res = await fetch(
        `${CARDS_API}/cards/by-handle/${encodeURIComponent(handle)}/refresh-memory`,
        { method: "POST", headers: { Authorization: `Bearer ${token}` } },
      );
      const data = await res.json();
      if (!data.connected) {
        setConnected(false);
        showToast("ZYND memory isn't connected to this account yet");
        return;
      }
      const next: Facts = Array.isArray(data.zynd_memory) ? data.zynd_memory : [];
      applyFacts(next);
      showToast(next.length > 0 ? `Synced — ${next.length} facts on your card` : "Synced — nothing public yet", "ok");
    } catch {
      showToast("Memory sync failed — try again", "err");
    } finally {
      setSyncing(false);
    }
  }

  async function applySnapshot(snapshot: MemorySnapshot) {
    if (snapshot === null) {
      await sync();
      return;
    }
    applyFacts(snapshot);
    showToast(`Synced — ${snapshot.length} fact${snapshot.length === 1 ? "" : "s"} on your card`, "ok");
  }

  const groups = ownerFactGroups(facts, details);
  const count = ownerFactCount(groups);
  const syncedAgo = lastSync ? formatAgo(lastSync, now) : "";

  return (
    <>
      <Card id="inbox" title="Facts to review"
        hint="Your coding agents suggested these. Publish adds one to your public card; Dismiss keeps it private.">
        <SuggestedFactsReview onChanged={applySnapshot} onCount={onReviewCount} />
      </Card>

      <Card id="memory" title="Memory on your card" hint="Public facts AI agents read when they work with you."
        action={
          <button type="button" className="pe-btn pe-btn-secondary pe-btn-sm" onClick={sync} disabled={syncing}>
            {syncing ? <Loader2 size={15} className="pe-spin" /> : <RefreshCw size={15} />}
            {syncing ? "Syncing…" : "Sync"}
          </button>
        }>
        {count > 0 ? (
          <>
            <div className="pe-mem-status">
              <span className="pe-dot" />
              <strong>{count} fact{count === 1 ? "" : "s"} on your public card</strong>
              {syncedAgo && <span>· synced {syncedAgo}</span>}
            </div>
            <OwnerMemoryList groups={groups} />
          </>
        ) : (
          <p className="pe-empty">
            {connected === false
              ? "ZYND memory isn't connected to this account yet."
              : connected
                ? "Synced. Nothing public yet — publish a fact above and it shows up here."
                : "Nothing public yet. Publish a fact above, sync, or import from a memory key."}
          </p>
        )}
        <div className="pe-import">
          {showImport ? (
            <MemoryProviderOnboard firstName={firstName} handle={handle} tone="light" compact
              onSkip={() => setShowImport(false)}
              onImported={(imported) => {
                applyFacts(imported as Facts);
                setShowImport(false);
              }} />
          ) : (
            <p className="pe-note">
              Using mem0, Zep, Letta or supermemory?{" "}
              <button type="button" className="pe-btn-link" onClick={() => setShowImport(true)}>Import from a memory key</button>
            </p>
          )}
        </div>
      </Card>

      <Card id="connect-mcp" title="Connect an assistant"
        hint="Let Claude, ChatGPT, Cursor and others use your memory and card, find people, and message your connections.">
        <McpConnectPanel />
      </Card>
    </>
  );
}
