import { ImageResponse } from "next/og";
import { createClient } from "@/lib/supabase/server";
import { ownerRequest } from "@/lib/owner-home";
import { fetchPublicRecap, type Recap } from "@/lib/recaps";
import { RecapArt } from "@/components/recaps/recap-art";

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[\da-f-]{36}$/i.test(id)) return new Response("Not found", { status: 404 });
  const query = new URL(request.url).searchParams;
  let recap: Recap | null;
  try {
    if (query.get("preview") === "1") {
      const client = await createClient();
      const { data: { session } } = await client.auth.getSession();
      if (!session?.access_token) return new Response("Unauthorized", { status: 401, headers: { "Cache-Control": "no-store" } });
      recap = await ownerRequest<Recap>(`mine/recaps/${id}`, session.access_token);
    } else {
      recap = await fetchPublicRecap(query.get("handle") || "", id);
    }
  } catch {
    return new Response("Recap unavailable", { status: 503, headers: { "Cache-Control": "no-store" } });
  }
  if (!recap) return new Response("Not found", { status: 404, headers: { "Cache-Control": "no-store" } });
  return new ImageResponse(<RecapArt recap={recap} />, { width: 1200, height: 630, headers: {
    "Cache-Control": "private, no-store",
    ...(query.get("download") === "1" ? { "Content-Disposition": `attachment; filename="zynd-recap-${recap.period}.png"` } : {}),
  } });
}
