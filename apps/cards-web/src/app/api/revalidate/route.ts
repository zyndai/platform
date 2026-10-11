import { revalidatePath } from "next/cache";

export async function POST(req: Request) {
  const secret = process.env.WEB_REVALIDATE_SECRET || "";
  const auth = req.headers.get("authorization") || "";
  if (!secret || auth !== `Bearer ${secret}`) {
    return Response.json({ error: "unauthorized" }, { status: 401 });
  }
  let handle = "";
  let alias = "";
  try {
    const body = (await req.json()) as { handle?: string; alias?: string };
    handle = (body.handle || "").replace(/^@/, "").trim();
    alias = (body.alias || "").replace(/^@/, "").trim().toLowerCase();
  } catch {
    handle = "";
    alias = "";
  }
  if (!handle || handle.includes("/") || handle.includes(".")) {
    return Response.json({ error: "handle required" }, { status: 422 });
  }
  revalidatePath(`/p/${handle}`);
  revalidatePath(`/p/${handle}/data.json`);
  revalidatePath(`/p/${handle}/opengraph-image`);
  revalidatePath(`/p/${handle}/twitter-image`);
  revalidatePath(`/p/${handle}/badge.svg`);
  revalidatePath(`/p/${handle}/vcard`);
  if (alias && !alias.includes("/") && !alias.includes(".") && alias.length >= 2) {
    revalidatePath(`/${alias}`);
  }
  return Response.json({ ok: true, handle, ...(alias ? { alias } : {}) });
}
