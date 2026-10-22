"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { createClient } from "@/lib/supabase/client";
import { MEMORY_API } from "@/lib/memory";
import styles from "./ProposalReview.module.css";

type Action = "save_memory" | "publish_card_fact";
type Proposal = {
  id: string;
  action: Action;
  text: string;
  public_text?: string;
  expires_at: string;
  status: string;
  version: number;
};
type Preview = Omit<Proposal, "id" | "status"> & { nonce: string };
class SignInRequired extends Error {}

export function ProposalReview({ id }: { id: string }) {
  const { ready, user } = useAuth();
  return (
    <main className={styles.page}>
      <section className={styles.panel} aria-labelledby="review-title">
        <p className={styles.eyebrow}>ZYND / AI ASSISTANT</p>
        <h1 id="review-title">Review your proposal</h1>
        {!ready ? <p role="status">Checking your session...</p> : !user ? (
          <SignIn id={id} />
        ) : <SignedInReview key={`${user.id}:${id}`} id={id} />}
      </section>
    </main>
  );
}

function SignIn({ id }: { id: string }) {
  return <div>
    <p>Sign in to the Zynd account connected to your AI assistant to review this proposal.</p>
    <Link className={styles.primary} href={`/auth?next=${encodeURIComponent(`/review/${encodeURIComponent(id)}`)}`}>
      Sign in to review
    </Link>
  </div>;
}

function SignedInReview({ id }: { id: string }) {
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [needsLogin, setNeedsLogin] = useState(false);
  const [result, setResult] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const inFlight = useRef(false);

  async function request<T>(suffix = "", body?: object, signal?: AbortSignal): Promise<T> {
    const { data } = await createClient().auth.getSession();
    if (!data.session) {
      throw new SignInRequired("Your session has expired. Sign in again to continue.");
    }
    const response = await fetch(`${MEMORY_API}/me/plugin/proposals/${encodeURIComponent(id)}${suffix}`, {
      method: body ? "POST" : "GET",
      headers: {
        Authorization: `Bearer ${data.session.access_token}`,
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      cache: "no-store",
      referrerPolicy: "no-referrer",
      signal,
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (response.status === 401) throw new SignInRequired("Your session has expired. Sign in again to continue.");
    if (!response.ok) {
      const messages: Record<number, string> = {
        401: "Your session has expired. Sign in again to continue.",
        403: "This proposal belongs to another account. Sign in with the account connected to your AI assistant.",
        404: "This proposal is unavailable. Check the link or ask your AI assistant for a new proposal.",
        409: "This proposal changed or was already decided. Reload to review its current state.",
        410: "This proposal or confirmation has expired. Ask your AI assistant for a new proposal.",
        422: "This text cannot be published as a card fact. Reject it and ask your AI assistant for a new proposal.",
      };
      throw new Error(messages[response.status] || "Could not complete the request. Please try again.");
    }
    return response.json() as Promise<T>;
  }

  useEffect(() => {
    const controller = new AbortController();
    void request<Proposal>("", undefined, controller.signal).then((data) => {
      if (controller.signal.aborted) return;
      setProposal(data);
    }).catch((err: unknown) => {
      if (!controller.signal.aborted) {
        setNeedsLogin(err instanceof SignInRequired);
        setError(err instanceof Error ? err.message : "Could not load this proposal.");
      }
    });
    const clock = window.setInterval(() => setNow(Date.now()), 1000);
    return () => { controller.abort(); window.clearInterval(clock); };
    // A new account or proposal remounts this component.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const expired = !!proposal && (!Number.isFinite(Date.parse(proposal.expires_at)) || Date.parse(proposal.expires_at) <= now);
  const previewExpired = !!preview && (!Number.isFinite(Date.parse(preview.expires_at)) || Date.parse(preview.expires_at) <= now);
  const supported = proposal?.action === "save_memory" || proposal?.action === "publish_card_fact";
  const publish = proposal?.action === "publish_card_fact";
  const pending = proposal?.status === "pending_review";

  async function act(decision?: "approve" | "reject") {
    if (inFlight.current || !proposal || !supported || !pending || Date.parse(proposal.expires_at) <= Date.now()) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      if (!decision) {
        setPreview(null);
        const next = await request<Preview>("/preview", publish ? { public_text: proposal.public_text } : {});
        if (next.action !== proposal.action || next.version !== proposal.version || !next.nonce ||
            !next.text || (publish && !next.public_text) || !(Date.parse(next.expires_at) > Date.now())) {
          throw new Error("The preview is no longer valid. Reload and review this proposal again.");
        }
        setPreview(next);
      } else {
        let confirmation = preview;
        // Rejection also uses a server-bound nonce, but never submits approval.
        if (decision === "reject" && (!confirmation || Date.parse(confirmation.expires_at) <= Date.now())) {
          confirmation = await request<Preview>("/preview", {});
        }
        if (!confirmation?.nonce || !(Date.parse(confirmation.expires_at) > Date.now())) {
          setPreview(null);
          throw new Error("Your confirmation expired. Preview the proposal again.");
        }
        const outcome = await request<{ status: string }>("/decision", { nonce: confirmation.nonce, decision });
        setPreview(null);
        setResult(outcome.status);
      }
    } catch (err) {
      if (decision) setPreview(null);
      setNeedsLogin(err instanceof SignInRequired);
      setError(err instanceof Error ? err.message : "Could not complete the request.");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  if (needsLogin) return <SignIn id={id} />;
  if (result) return <div role="status"><h2>{result === "rejected" ? "Proposal rejected" : result === "saved_privately" ? "Saved to private memory" : result === "sync_pending" ? "Publication approved" : "Proposal updated"}</h2><p>{result === "rejected" ? "Nothing was saved or published." : result === "sync_pending" ? "Your exact text was approved. Your public card update is pending." : result === "saved_privately" ? "Your memory was saved privately. Nothing was published to your card." : "This proposal has been decided."}</p></div>;

  return <>
    {error && <p className={styles.error} role="alert">{error}</p>}
    {!proposal ? (!error && <p role="status">Loading proposal...</p>) : <>
      <p className={styles.eyebrow}>{publish ? "PUBLIC CARD FACT" : "PRIVATE MEMORY"}</p>
      <p>{publish ? "Publishing makes the exact text below visible on your public card and discoverable by people and AI agents." : "Saving adds this text to your private memory. It will not publish anything to your card."}</p>
      <h2>Proposed memory</h2>
      <div className={styles.text}>{proposal.text}</div>
      {!pending ? <p role="status">This proposal is {proposal.status}. It cannot be submitted again.</p> : expired ? <p role="status">This proposal has expired. Ask your AI assistant for a new proposal.</p> : !supported ? <p role="alert">This proposal type is unsupported.</p> : <>
        {publish && !preview && <><h2>Proposed public card text</h2><div className={styles.text}>{proposal.public_text}</div><p>To change this text, reject this proposal and ask your AI assistant for a new one.</p></>}
        {preview ? <div className={styles.confirmation}>
          <h2>{publish ? "Step 2: Confirm publication" : "Confirm private save"}</h2>
          <p>{publish ? "This exact text will be public:" : "This exact text will be saved privately:"}</p>
          <div className={styles.text}>{publish ? preview.public_text : preview.text}</div>
          {previewExpired && <p role="alert">This confirmation expired. Go back and preview again.</p>}
          <div className={styles.actions}>
            <button className={styles.primary} disabled={busy || previewExpired} onClick={() => void act("approve")}>
              {busy ? "Submitting..." : publish ? "Publish this exact text" : "Save to private memory"}
            </button>
            <button disabled={busy} onClick={() => setPreview(null)}>Back to review</button>
          </div>
        </div> : <button className={styles.primary} disabled={busy || (publish && !proposal.public_text?.trim())} onClick={() => void act()}>
          {busy ? "Preparing..." : publish ? "Step 1: Preview publication" : "Review private save"}
        </button>}
        <div className={styles.actions}>
          <button disabled={busy} onClick={() => void act("reject")}>Reject proposal</button>
          <span className={styles.expiry}>Expires {new Date(proposal.expires_at).toLocaleString()}</span>
        </div>
      </>}
    </>}
  </>;
}
