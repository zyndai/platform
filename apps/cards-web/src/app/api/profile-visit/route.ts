import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function POST(req: NextRequest) {
  const origin = req.headers.get("origin");
  if (origin) {
    try {
      if (new URL(origin).host !== req.headers.get("host")) return new Response(null, { status: 403 });
    } catch { return new Response(null, { status: 403 }); }
  }
  const { data: { session } } = await (await createClient()).auth.getSession();
  if (!session) return new Response(null, { status: 204 });
  try {
    const { handle, visit_id } = await req.json();
    if (typeof handle !== "string" || !/^[a-zA-Z0-9_-]{1,80}$/.test(handle) || typeof visit_id !== "string") {
      return new Response(null, { status: 400 });
    }
    const api = (process.env.NEXT_PUBLIC_API_URL || "https://api.zynd.ai").replace(/\/$/, "");
    const upstream = await fetch(`${api}/cards/by-handle/${encodeURIComponent(handle)}/visit`, {
      method: "POST", cache: "no-store", signal: AbortSignal.timeout(10_000),
      headers: { Authorization: `Bearer ${session.access_token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ visit_id }),
    });
    return new Response(null, { status: upstream.status });
  } catch {
    return NextResponse.json({ detail: "Visit recording unavailable" }, { status: 503 });
  }
}
