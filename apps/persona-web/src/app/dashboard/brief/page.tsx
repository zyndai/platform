"use client";

import { useEffect, useState } from "react";
import { ExternalLink } from "lucide-react";
import { Button, EmptyState } from "@/components/ui";
import { getSupabase } from "@/lib/supabase";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface BriefInfo {
  present: boolean;
  url?: string;
  title?: string;
}

export default function BriefPage() {
  const [brief, setBrief] = useState<BriefInfo | null>(null);
  const [working, setWorking] = useState<"create" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      const sb = getSupabase();
      const {
        data: { session },
      } = await sb.auth.getSession();
      if (!session?.access_token) {
        setBrief({ present: false });
        return;
      }
      const res = await fetch(`${API}/api/brief/me`, {
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      if (res.ok) setBrief(await res.json());
      else setBrief({ present: false });
    })();
  }, []);

  const handleCreate = async () => {
    setWorking("create");
    setError(null);
    const sb = getSupabase();
    const { data: { session } } = await sb.auth.getSession();
    const jwt = session?.access_token;
    if (!jwt) {
      setError("Not signed in.");
      setWorking(null);
      return;
    }
    const res = await fetch(`${API}/api/brief/create`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${jwt}`,
      },
      body: JSON.stringify({}),
    });
    if (res.ok) {
      const data = await res.json();
      setBrief({ present: true, url: data.url, title: data.title });
      setWorking(null);
      return;
    }
    if (res.status === 403) {
      // Need Drive scope — bounce through OAuth.
      window.location.href =
        `${API}/api/oauth/google/authorize?features=calendar,docs&token=${jwt}`;
      return;
    }
    setError((await res.text().catch(() => "")) || `HTTP ${res.status}`);
    setWorking(null);
  };

  if (brief === null) {
    return null;
  }

  if (brief.present && brief.url) {
    return (
      <div className="brief-page">
        <div className="brief-card">
          <h2 className="brief-card-title">{brief.title || "Your brief"}</h2>
          <p className="brief-card-body">
            Living in your Drive. Edit anytime — I&apos;ll re-read whenever it changes.
          </p>
          <a href={brief.url} target="_blank" rel="noopener noreferrer">
            <Button rightIcon={<ExternalLink size={14} strokeWidth={1.5} />}>
              Open my brief
            </Button>
          </a>
        </div>
      </div>
    );
  }

  return (
    <>
      <EmptyState
        title="Your brief is blank."
        body="Even one line helps me match better — tell me what you're working on."
        action={
          <>
            <Button onClick={handleCreate} disabled={working === "create"}>
              {working === "create" ? "Creating…" : "Create my brief"}
            </Button>
            {error && (
              <span className="body-s" style={{ color: "var(--danger)" }}>
                {error}
              </span>
            )}
          </>
        }
      />
    </>
  );
}
