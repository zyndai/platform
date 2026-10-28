"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { CARDS_API } from "@/lib/cards";

type Status = "idle" | "busy" | "done" | "error";

/** Owner-only, under stale Working on chips: "Still working on this? Confirm · Update".
 *  Confirm resets the freshness stamp (cards-api POST …/working-on/confirm) without
 *  changing the list; Update opens the editor's Interests section. The parent renders
 *  this only for the signed-in owner; cards-api checks ownership again. */
export function StaleWorkingOnPrompt({ handle, className }: { handle: string; className?: string }) {
  const router = useRouter();
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState("");

  async function confirm() {
    setStatus("busy");
    setError("");
    try {
      const { data: { session } } = await createClient().auth.getSession();
      if (!session?.access_token) {
        setStatus("error");
        setError("Sign in again to confirm.");
        return;
      }
      const res = await fetch(`${CARDS_API}/cards/by-handle/${encodeURIComponent(handle)}/working-on/confirm`, {
        method: "POST",
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
        setStatus("error");
        setError(typeof body.detail === "string" ? body.detail : "Couldn't confirm. Try again.");
        return;
      }
      setStatus("done");
      router.refresh();
    } catch (cause) {
      console.warn("working_on confirm failed", cause);
      setStatus("error");
      setError("Couldn't confirm. Try again.");
    }
  }

  if (status === "done") {
    return <p className={className} role="status">Thanks, marked as current.</p>;
  }
  return (
    <p className={className}>
      Still working on this?{" "}
      <button type="button" className="stale-wo-action" onClick={confirm} disabled={status === "busy"} aria-busy={status === "busy"}>
        {status === "busy" ? "Confirming…" : "Confirm"}
      </button>
      {" · "}
      <a className="stale-wo-action" href={`/p/${encodeURIComponent(handle)}/edit#signals`}>Update</a>
      {status === "error" && <span role="alert" className="stale-wo-error"> {error}</span>}
    </p>
  );
}
