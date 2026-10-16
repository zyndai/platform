import { NextRequest, NextResponse } from "next/server";

export async function POST(req: NextRequest) {
  try {
    const body = await req.text();
    if (new TextEncoder().encode(body).length > 64 * 1024) return new Response(null, { status: 413 });
    const api = (process.env.NEXT_PUBLIC_API_URL || "https://api.zynd.ai").replace(/\/$/, "");
    const upstream = await fetch(`${api}/events`, {
      method: "POST", cache: "no-store", signal: AbortSignal.timeout(10_000),
      headers: { "Content-Type": "application/json", "User-Agent": req.headers.get("user-agent") || "",
        "x-forwarded-for": req.headers.get("x-forwarded-for") || "" }, body,
    });
    return new Response(null, { status: upstream.status });
  } catch {
    return NextResponse.json({ error: "Event collection unavailable" }, { status: 503 });
  }
}
