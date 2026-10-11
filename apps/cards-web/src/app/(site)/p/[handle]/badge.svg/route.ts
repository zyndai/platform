import { NextResponse } from "next/server";
import { fetchCardByHandle } from "@/lib/cards";

export const revalidate = 3600;

interface RouteProps {
  params: Promise<{ handle: string }>;
}

function escapeXml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export async function GET(_req: Request, { params }: RouteProps) {
  const { handle } = await params;
  const card = await fetchCardByHandle(handle);
  const label = (card?.identity?.name || card?.handle || handle).trim() || "Zynd";
  const short = label.length > 22 ? `${label.slice(0, 19)}…` : label;

  const left = "Zynd";
  const right = short;
  const leftW = 48;
  const rightW = Math.max(70, Math.min(180, 10 + right.length * 7));
  const height = 20;
  const width = leftW + rightW;

  const svg = `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" role="img" aria-label="${escapeXml(left)}: ${escapeXml(right)}">
  <title>${escapeXml(left)}: ${escapeXml(right)}</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#fff" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r"><rect width="${width}" height="${height}" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="${leftW}" height="${height}" fill="#555"/>
    <rect x="${leftW}" width="${rightW}" height="${height}" fill="#7B72E9"/>
    <rect width="${width}" height="${height}" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" text-rendering="geometricPrecision" font-size="11">
    <text x="${leftW / 2}" y="14">${escapeXml(left)}</text>
    <text x="${leftW + rightW / 2}" y="14">${escapeXml(right)}</text>
  </g>
</svg>`;

  return new NextResponse(svg, {
    status: 200,
    headers: {
      "Content-Type": "image/svg+xml; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
    },
  });
}
