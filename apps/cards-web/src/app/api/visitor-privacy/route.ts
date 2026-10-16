import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

async function proxy(req: NextRequest, method: "GET" | "PATCH") {
  const origin = req.headers.get("origin");
  if (method === "PATCH" && origin) {
    try {
      if (new URL(origin).host !== req.headers.get("host")) return new Response(null, { status: 403 });
    } catch { return new Response(null, { status: 403 }); }
  }
  const { data: { session } } = await (await createClient()).auth.getSession();
  if (!session) return new Response(null, { status: 401 });
  try {
    const api = (process.env.NEXT_PUBLIC_API_URL || "https://api.zynd.ai").replace(/\/$/, "");
    const upstream = await fetch(`${api}/cards/mine/visitor-privacy`, {
      method, cache: "no-store", signal: AbortSignal.timeout(10_000),
      headers: { Authorization: `Bearer ${session.access_token}`, "Content-Type": "application/json" },
      ...(method === "PATCH" ? { body: await req.text() } : {}),
    });
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ detail: "Visitor privacy is unavailable" }, { status: 503 });
  }
}
export const GET = (req: NextRequest) => proxy(req, "GET");
export const PATCH = (req: NextRequest) => proxy(req, "PATCH");
