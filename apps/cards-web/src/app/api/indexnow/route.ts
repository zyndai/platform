import { NextRequest, NextResponse } from "next/server";

const INDEXNOW_KEY = "719dc68a3a793fd032b8c23bffba620c";
const SITE_URL = "https://cards.zynd.ai";

// Called fire-and-forget from the create flow after a new profile is published.
// Submits the new profile URL to Bing IndexNow so it's indexed within minutes.
export async function POST(req: NextRequest) {
  let handle: string | undefined;
  try {
    const body = await req.json();
    handle = typeof body.handle === "string" ? body.handle.trim() : undefined;
  } catch {
    return NextResponse.json({ error: "bad request" }, { status: 400 });
  }

  if (!handle) {
    return NextResponse.json({ error: "handle required" }, { status: 400 });
  }

  const urls = [`${SITE_URL}/p/${handle}`];

  try {
    const res = await fetch("https://api.indexnow.org/indexnow", {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({
        host: "cards.zynd.ai",
        key: INDEXNOW_KEY,
        keyLocation: `${SITE_URL}/${INDEXNOW_KEY}.txt`,
        urlList: urls,
      }),
      signal: AbortSignal.timeout(8000),
    });
    return NextResponse.json({ submitted: res.ok, status: res.status, urls });
  } catch {
    return NextResponse.json({ submitted: false, urls }, { status: 502 });
  }
}
