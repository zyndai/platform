import { NextResponse } from "next/server";
import { cardsSiteOrigin, fetchCardByHandle } from "@/lib/cards";
import { ownerHomeEnabled } from "@/lib/owner-home";

export const revalidate = 3600;

interface RouteProps {
  params: Promise<{ handle: string }>;
}

function vcardEscape(value: string): string {
  return value
    .replace(/\\/g, "\\\\")
    .replace(/\n/g, "\\n")
    .replace(/,/g, "\\,")
    .replace(/;/g, "\\;");
}

function splitName(full: string): { family: string; given: string } {
  const parts = full.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return { family: "", given: "" };
  if (parts.length === 1) return { family: parts[0], given: "" };
  return { given: parts.slice(0, -1).join(" "), family: parts[parts.length - 1] };
}

export async function GET(_req: Request, { params }: RouteProps) {
  const { handle } = await params;
  const card = await fetchCardByHandle(handle);
  if (!card) {
    return NextResponse.json({ detail: "not found" }, { status: 404 });
  }

  const name = (card.identity?.name || handle).trim();
  const { family, given } = splitName(name);
  const headline = (card.identity?.headline || "").trim();
  const profileUrl = `${cardsSiteOrigin()}/p/${encodeURIComponent(card.handle || handle)}`;
  const email = (card.identity?.links?.email || "").trim();
  const photo = (card.identity?.avatar_url || "").trim();

  const lines = [
    "BEGIN:VCARD",
    "VERSION:3.0",
    `FN:${vcardEscape(name)}`,
    `N:${vcardEscape(family)};${vcardEscape(given)};;;`,
  ];
  if (headline) lines.push(`TITLE:${vcardEscape(headline)}`);
  lines.push(`URL:${vcardEscape(profileUrl)}`);
  if (email && email.includes("@")) lines.push(`EMAIL;TYPE=INTERNET:${vcardEscape(email)}`);
  if (/^https?:\/\//i.test(photo)) lines.push(`PHOTO;VALUE=URI:${vcardEscape(photo)}`);
  lines.push("END:VCARD", "");

  const body = lines.join("\r\n");
  const safeFile = (card.handle || handle).replace(/[^a-zA-Z0-9._-]/g, "_");

  return new NextResponse(body, {
    status: 200,
    headers: {
      "Content-Type": "text/vcard; charset=utf-8",
      "Content-Disposition": `attachment; filename="${safeFile}.vcf"`,
      "Cache-Control": ownerHomeEnabled ? "no-store" : "public, max-age=3600",
    },
  });
}
