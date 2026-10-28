"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { CARDS_API } from "@/lib/cards";

type Status = "idle" | "busy" | "done" | "error";

/** Owner-only, under stale Working on chips: "Still working on this? Confirm · Update".
 *  Confirm resets the freshness stamp (cards-api POST …/working-on/confirm) without
 *  changing the list; Update opens the editor's Interests section. The parent renders
 *  this only for the signed-in owner; cards-api checks ownership again.
 *
 *  The parent keeps it mounted while the chips are fresh too (`stale` false), so the
 *  thanks survives the router.refresh() that un-dims them; it renders nothing then
 *  until a confirm happens. */
export function StaleWorkingOnPrompt({ handle, stale, className }: { handle: string; stale: boolean; className?: string }) {
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
        // 404: cards-api has stale signals turned off ("Stale signals are turned off") or
        // doesn't know the card; neither detail means anything to the owner.
        if (res.status === 404) setError("Confirm isn't available right now. Use Update instead.");
        else setError(typeof body.detail === "string" ? body.detail : "Couldn't confirm. Try again.");
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

  const confirmed = status === "done";
  if (!stale && !confirmed) return null;
  // The status region is already mounted when the thanks lands in it, so screen readers announce it.
  return (
    <>
      {!confirmed && (
        <p className={className}>
          Still working on this?{" "}
          <button type="button" className="stale-wo-action" onClick={confirm} disabled={status === "busy"} aria-busy={status === "busy"}>
            {status === "busy" ? "Confirming…" : "Confirm"}
          </button>
          {" · "}
          <a className="stale-wo-action" href={`/p/${encodeURIComponent(handle)}/edit#signals`}>Update</a>
          <span role="alert" className="stale-wo-error">{status === "error" ? ` ${error}` : ""}</span>
        </p>
      )}
      <div role="status" aria-live="polite">
        {confirmed && <p className={className}>Thanks, marked as current.</p>}
      </div>
    </>
  );
}
