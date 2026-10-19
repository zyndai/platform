"use client";

import { useState } from "react";
import Link from "next/link";
import { Link2 } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { cardsNetworkRequest, connectionRequestNotice, type CardConnection } from "@/lib/cards-network";

export function RequestConnection({ handle }: { handle: string }) {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState<"idle" | "busy" | "sent" | "error">("idle");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function submit() {
    setStatus("busy");
    setError("");
    try {
      const { data: { session } } = await createClient().auth.getSession();
      if (!session?.access_token) throw new Error("Sign in before sending a connection request.");
      const result = await cardsNetworkRequest<{ connection: CardConnection; existing: boolean }>("/connections", session.access_token, "POST", {
        target_handle: handle,
        message: message.trim() || undefined,
      });
      setNotice(connectionRequestNotice(result));
      setStatus("sent");
    } catch (failure) {
      setStatus("error");
      setError(failure instanceof Error ? failure.message : "Could not send the request");
    }
  }

  if (status === "sent") {
    return <p className="intro-request" role="status" style={{ margin: "20px 0", color: "#4f46e5" }}>{notice}. <Link href="/network">View your network</Link></p>;
  }

  return (
    <section className="intro-request" style={{ margin: "20px 0" }}>
      <button type="button" className="oh-button" onClick={() => setOpen((current) => !current)} aria-expanded={open}>
        <Link2 size={15} aria-hidden="true" /> Request connection
      </button>
      {open && (
        <div style={{ marginTop: 12, maxWidth: 460 }}>
          <p style={{ margin: "0 0 8px", fontSize: 13, color: "#666" }}>Connect with this verified Card. DMs become available after they accept.</p>
          <textarea aria-label="Connection note" value={message} onChange={(event) => setMessage(event.target.value)} maxLength={2000} placeholder="Optional note" style={{ width: "100%", minHeight: 80, padding: 10, borderRadius: 8, border: "1px solid #ddd" }} />
          <button type="button" className="oh-button" disabled={status === "busy"} onClick={() => void submit()} style={{ marginTop: 8 }}>
            {status === "busy" ? "Sending…" : "Send request"}
          </button>
          {status === "error" && <p role="alert" style={{ color: "#b91c1c", fontSize: 13 }}>{error}</p>}
        </div>
      )}
    </section>
  );
}
