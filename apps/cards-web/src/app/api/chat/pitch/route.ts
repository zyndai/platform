import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://api.zynd.ai";
// Only allow slug-safe handles — prevents path traversal / URL injection
const HANDLE_RE = /^[a-zA-Z0-9_-]{1,80}$/;

/** Visitor-facing messages for the statuses cards-api answers a pitch with; anything else is "Upstream error". */
const STATUS_MESSAGES: Record<number, string> = {
  403: "This card has no assistant",
  404: "Card not found",
  409: "This card doesn't ask for a pitch",
  503: "Chatbot unavailable",
};

export async function POST(req: NextRequest) {
  try {
    const { handle, pitch } = await req.json();

    if (!handle || !HANDLE_RE.test(handle) || typeof pitch !== "string") {
      return NextResponse.json({ error: "handle and pitch required" }, { status: 400 });
    }

    const res = await fetch(`${API_BASE}/v1/chat/${handle}/pitch`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-forwarded-for": req.headers.get("x-forwarded-for") ?? "",
      },
      body: JSON.stringify({ pitch }),
      cache: "no-store",
    });

    if (res.ok) return NextResponse.json(await res.json(), { headers: { "Cache-Control": "no-store" } });

    // These details are cards-api's own visitor-facing copy (length rule, which limit, "try again"); pass them through.
    if (res.status === 400 || res.status === 429 || res.status === 502) {
      const body = (await res.json().catch(() => ({}))) as { detail?: unknown };
      const error = typeof body.detail === "string" ? body.detail : "Couldn't check your pitch right now.";
      return NextResponse.json({ error }, { status: res.status });
    }
    const status = res.status in STATUS_MESSAGES ? res.status : 502;
    return NextResponse.json({ error: STATUS_MESSAGES[status] ?? "Upstream error" }, { status });
  } catch {
    return NextResponse.json({ error: "Internal error" }, { status: 500 });
  }
}
