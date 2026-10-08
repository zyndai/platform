import { revalidatePath } from "next/cache";

export async function POST(req: Request) {
  const secret = process.env.WEB_REVALIDATE_SECRET || "";
  const auth = req.headers.get("authorization") || "";
  if (!secret || auth !== `Bearer ${secret}`) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  let handle = "";
  try {
    const body = (await req.json()) as { handle?: string };
    handle = (body.handle || "").replace(/^@/, "").trim();
  } catch {
    handle = "";
  }
  if (!handle) {
    return Response.json({ error: "handle required" }, { status: 422 });
  }
  revalidatePath(`/p/${handle}`);
  revalidatePath(`/p/${handle}/data.json`);
  return Response.json({ ok: true, handle });
}
