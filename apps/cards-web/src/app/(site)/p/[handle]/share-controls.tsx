"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Check, Copy, Download, FileText, Link2, Mail, Maximize2, QrCode, Share2, X } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";

import { withShareRef } from "@/lib/attr";
import { cardsSiteOrigin } from "@/lib/cards";
import { track } from "@/lib/track";
import { ResumePicker } from "./resume-picker";
import type { ResumeData } from "./resume-pdf";

type ShareTab = "link" | "qr" | "card" | "embed";

const TABS: { id: ShareTab; label: string }[] = [
  { id: "link", label: "Link" },
  { id: "qr", label: "QR" },
  { id: "card", label: "Card image" },
  { id: "embed", label: "Embed & email" },
];

// ── Canvas primitives ────────────────────────────────────────────────────────

function rrect(
  ctx: CanvasRenderingContext2D,
  x: number, y: number, w: number, h: number, r: number
) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

async function loadImage(src: string): Promise<HTMLImageElement | null> {
  return new Promise((resolve) => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => resolve(img);
    img.onerror = () => {
      const img2 = new Image();
      img2.onload = () => resolve(img2);
      img2.onerror = () => resolve(null);
      img2.src = src;
    };
    img.src = src;
  });
}

function drawZLogo(ctx: CanvasRenderingContext2D, cx: number, cy: number, r: number) {
  const g = ctx.createLinearGradient(cx - r, cy - r, cx + r, cy + r);
  g.addColorStop(0, "#818cf8");
  g.addColorStop(1, "#4338ca");
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.moveTo(cx + r * 0.28, cy - r);
  ctx.lineTo(cx - r, cy + r * 0.10);
  ctx.lineTo(cx - r * 0.10, cy + r * 0.10);
  ctx.lineTo(cx - r * 0.28, cy + r);
  ctx.lineTo(cx + r, cy - r * 0.10);
  ctx.lineTo(cx + r * 0.10, cy - r * 0.10);
  ctx.closePath();
  ctx.fill();
}

// ── Icon draw helpers ────────────────────────────────────────────────────────

function iconFolder(ctx: CanvasRenderingContext2D, cx: number, cy: number) {
  ctx.fillStyle = "#059669";
  // tab
  ctx.beginPath();
  ctx.moveTo(cx - 11, cy - 4);
  ctx.lineTo(cx - 11, cy - 8);
  ctx.lineTo(cx - 4, cy - 8);
  ctx.lineTo(cx - 1, cy - 4);
  ctx.closePath();
  ctx.fill();
  // body
  rrect(ctx, cx - 11, cy - 4, 22, 14, 3);
  ctx.fill();
}

function iconPeople(ctx: CanvasRenderingContext2D, cx: number, cy: number) {
  ctx.fillStyle = "#6366f1";
  ctx.beginPath(); ctx.arc(cx + 4, cy - 6, 5, 0, Math.PI * 2); ctx.fill();
  ctx.beginPath(); ctx.arc(cx + 7, cy + 6, 7, Math.PI, 0); ctx.closePath(); ctx.fill();
  ctx.fillStyle = "#a5b4fc";
  ctx.beginPath(); ctx.arc(cx - 4, cy - 6, 5, 0, Math.PI * 2); ctx.fill();
  ctx.beginPath(); ctx.arc(cx - 2, cy + 6, 7, Math.PI, 0); ctx.closePath(); ctx.fill();
}

function iconLightning(ctx: CanvasRenderingContext2D, cx: number, cy: number) {
  ctx.fillStyle = "#d97706";
  ctx.beginPath();
  ctx.moveTo(cx + 4, cy - 12);
  ctx.lineTo(cx - 5, cy + 1);
  ctx.lineTo(cx + 1, cy + 1);
  ctx.lineTo(cx - 4, cy + 12);
  ctx.lineTo(cx + 5, cy - 1);
  ctx.lineTo(cx - 1, cy - 1);
  ctx.closePath();
  ctx.fill();
}

function iconLink(ctx: CanvasRenderingContext2D, cx: number, cy: number) {
  ctx.strokeStyle = "#475569";
  ctx.lineWidth = 2.5;
  ctx.lineCap = "round";
  // two chain links
  ctx.beginPath();
  ctx.moveTo(cx - 9, cy - 4); ctx.lineTo(cx - 3, cy - 4);
  ctx.arc(cx - 3, cy, 4, -Math.PI/2, Math.PI/2);
  ctx.lineTo(cx - 9, cy + 4);
  ctx.arc(cx - 9, cy, 4, Math.PI/2, -Math.PI/2);
  ctx.closePath();
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(cx + 3, cy - 4); ctx.lineTo(cx + 9, cy - 4);
  ctx.arc(cx + 9, cy, 4, -Math.PI/2, Math.PI/2);
  ctx.lineTo(cx + 3, cy + 4);
  ctx.arc(cx + 3, cy, 4, Math.PI/2, -Math.PI/2);
  ctx.closePath();
  ctx.stroke();
}

function iconBarChart(ctx: CanvasRenderingContext2D, cx: number, cy: number) {
  ctx.fillStyle = "#db2777";
  const bars = [{ x: -9, h: 9 }, { x: -2, h: 15 }, { x: 5, h: 6 }];
  for (const b of bars) {
    rrect(ctx, cx + b.x, cy + 9 - b.h, 6, b.h, 2);
    ctx.fill();
  }
}

function iconSparkle(ctx: CanvasRenderingContext2D, cx: number, cy: number) {
  ctx.fillStyle = "#7c3aed";
  for (let i = 0; i < 4; i++) {
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate((i / 4) * Math.PI * 2);
    ctx.beginPath();
    ctx.moveTo(0, -12);
    ctx.quadraticCurveTo(2.5, -4, 0, 0);
    ctx.quadraticCurveTo(-2.5, -4, 0, -12);
    ctx.fill();
    ctx.restore();
  }
}

// ── Identity card builder ────────────────────────────────────────────────────

async function buildIdentityCard(
  qrSvg: SVGSVGElement,
  name: string,
  handle: string,
  avatarSrc: string | null | undefined
): Promise<Blob | null> {
  const DPR = 2;
  const W = 860, H = 1080;
  const canvas = document.createElement("canvas");
  canvas.width = W * DPR;
  canvas.height = H * DPR;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  ctx.scale(DPR, DPR);

  // Background
  const bg = ctx.createLinearGradient(0, 0, W, H);
  bg.addColorStop(0, "#eef2ff");
  bg.addColorStop(0.6, "#f5f7ff");
  bg.addColorStop(1, "#f0f4ff");
  rrect(ctx, 0, 0, W, H, 0);
  ctx.fillStyle = bg;
  ctx.fill();

  // Zynd logo (top-left)
  drawZLogo(ctx, 66, 72, 16);
  ctx.fillStyle = "#0f172a";
  ctx.font = "bold 26px Arial, sans-serif";
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  ctx.fillText("Zynd", 90, 72);

  // LIVING PROFILE pill (top-right)
  const pillTxt = "LIVING PROFILE";
  ctx.font = "bold 11px monospace";
  const pillW = ctx.measureText(pillTxt).width + 36;
  const pillH = 28;
  const pillX = W - 52 - pillW;
  const pillY = 58;
  rrect(ctx, pillX, pillY, pillW, pillH, 14);
  ctx.fillStyle = "#f0fdf4";
  ctx.fill();
  ctx.strokeStyle = "#86efac";
  ctx.lineWidth = 1.5;
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(pillX + 16, pillY + pillH / 2, 4, 0, Math.PI * 2);
  ctx.fillStyle = "#22c55e";
  ctx.fill();
  ctx.fillStyle = "#15803d";
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  ctx.fillText(pillTxt, pillX + 26, pillY + pillH / 2);

  // Avatar
  const avS = 128, avR = 22;
  const avX = W / 2 - avS / 2;
  const avY = 128;
  const avCx = W / 2, avCy = avY + avS / 2;

  ctx.save();
  rrect(ctx, avX, avY, avS, avS, avR);
  ctx.clip();

  let avatarDrawn = false;
  if (avatarSrc) {
    const img = await loadImage(avatarSrc);
    if (img) {
      ctx.drawImage(img, avX, avY, avS, avS);
      avatarDrawn = true;
    }
  }
  if (!avatarDrawn) {
    const fb = ctx.createLinearGradient(avX, avY, avX + avS, avY + avS);
    fb.addColorStop(0, "#6366f1");
    fb.addColorStop(1, "#4338ca");
    ctx.fillStyle = fb;
    ctx.fillRect(avX, avY, avS, avS);
    const initials = name.trim().split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
    ctx.fillStyle = "#fff";
    ctx.font = "bold 40px Arial, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(initials, avCx, avCy);
  }
  ctx.restore();

  // Avatar border
  rrect(ctx, avX, avY, avS, avS, avR);
  ctx.strokeStyle = "rgba(99,102,241,0.22)";
  ctx.lineWidth = 2.5;
  ctx.stroke();

  // Gold verified badge
  const bdx = avX + avS - 4;
  const bdy = avY + avS - 4;
  ctx.beginPath();
  ctx.arc(bdx, bdy, 13, 0, Math.PI * 2);
  ctx.fillStyle = "#fbbf24";
  ctx.fill();
  ctx.strokeStyle = "#fff";
  ctx.lineWidth = 2.5;
  ctx.stroke();
  ctx.strokeStyle = "#fff";
  ctx.lineWidth = 2.2;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.beginPath();
  ctx.moveTo(bdx - 5, bdy + 0.5);
  ctx.lineTo(bdx - 1, bdy + 4.5);
  ctx.lineTo(bdx + 5.5, bdy - 4);
  ctx.stroke();

  // Name
  ctx.textAlign = "center";
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = "#0f172a";
  ctx.font = "bold 22px Arial, sans-serif";
  ctx.fillText(name, W / 2, avY + avS + 40);
  ctx.fillStyle = "#6366f1";
  ctx.font = "600 13px monospace";
  ctx.fillText(`zynd.ai/${handle}`, W / 2, avY + avS + 62);

  // QR code
  const clone = qrSvg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  const svgBlob = new Blob([new XMLSerializer().serializeToString(clone)], {
    type: "image/svg+xml;charset=utf-8",
  });
  const svgUrl = URL.createObjectURL(svgBlob);
  const qrImg = await new Promise<HTMLImageElement | null>((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = svgUrl;
  });
  URL.revokeObjectURL(svgUrl);

  const qrSide = 340;
  const qrPad = 18;
  const cardW = qrSide + qrPad * 2;
  const cardH = qrSide + qrPad * 2;
  const cardX = W / 2 - cardW / 2;
  const cardY = avY + avS + 86;

  // White QR card with soft shadow
  ctx.shadowColor = "rgba(99,102,241,0.14)";
  ctx.shadowBlur = 28;
  rrect(ctx, cardX, cardY, cardW, cardH, 20);
  ctx.fillStyle = "#ffffff";
  ctx.fill();
  ctx.shadowBlur = 0;

  if (qrImg) {
    ctx.drawImage(qrImg, cardX + qrPad, cardY + qrPad, qrSide, qrSide);
  }

  // Corner brackets
  const bLen = 28;
  const bOff = -5;
  ctx.strokeStyle = "#6366f1";
  ctx.lineWidth = 3.5;
  ctx.lineCap = "round";
  const corners = [
    [cardX + bOff, cardY + bOff, 1, 1],
    [cardX + cardW - bOff, cardY + bOff, -1, 1],
    [cardX + bOff, cardY + cardH - bOff, 1, -1],
    [cardX + cardW - bOff, cardY + cardH - bOff, -1, -1],
  ] as const;
  for (const [bx, by, sx, sy] of corners) {
    ctx.beginPath();
    ctx.moveTo(bx + sx * bLen, by);
    ctx.lineTo(bx + sx * 7, by);
    ctx.quadraticCurveTo(bx, by, bx, by + sy * 7);
    ctx.lineTo(bx, by + sy * bLen);
    ctx.stroke();
  }

  // Zynd Z in QR center
  const qrCx = W / 2;
  const qrCy = cardY + qrPad + qrSide / 2;
  ctx.shadowColor = "rgba(99,102,241,0.18)";
  ctx.shadowBlur = 8;
  ctx.beginPath();
  ctx.arc(qrCx, qrCy, 21, 0, Math.PI * 2);
  ctx.fillStyle = "#ffffff";
  ctx.fill();
  ctx.shadowBlur = 0;
  drawZLogo(ctx, qrCx, qrCy, 11);

  // Side icons + dashed connectors
  const tS = 52, tR = 14;
  const lX = 56;
  const rX = W - 56 - tS;
  const qrMidY = cardY + cardH / 2;
  const rows = [-82, 0, 82];

  const leftDef: Array<{ bg: string; fn: (c: CanvasRenderingContext2D, x: number, y: number) => void }> = [
    { bg: "#d1fae5", fn: iconFolder },
    { bg: "#e0e7ff", fn: iconPeople },
    { bg: "#fef9c3", fn: iconLightning },
  ];
  const rightDef: Array<{ bg: string; fn: (c: CanvasRenderingContext2D, x: number, y: number) => void }> = [
    { bg: "#f1f5f9", fn: iconLink },
    { bg: "#fce7f3", fn: iconBarChart },
    { bg: "#ede9fe", fn: iconSparkle },
  ];

  for (let i = 0; i < 3; i++) {
    const ty = qrMidY + rows[i] - tS / 2;
    const tcy = ty + tS / 2;

    // Left tile
    rrect(ctx, lX, ty, tS, tS, tR);
    ctx.fillStyle = leftDef[i].bg;
    ctx.fill();
    leftDef[i].fn(ctx, lX + tS / 2, tcy);

    // Left dashed line
    ctx.save();
    ctx.setLineDash([4, 5]);
    ctx.strokeStyle = "#cbd5e1";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(lX + tS + 8, tcy);
    ctx.lineTo(cardX + bOff - 14, qrMidY + rows[i]);
    ctx.stroke();
    ctx.restore();

    // Right tile
    rrect(ctx, rX, ty, tS, tS, tR);
    ctx.fillStyle = rightDef[i].bg;
    ctx.fill();
    rightDef[i].fn(ctx, rX + tS / 2, tcy);

    // Right dashed line
    ctx.save();
    ctx.setLineDash([4, 5]);
    ctx.strokeStyle = "#cbd5e1";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(rX - 8, tcy);
    ctx.lineTo(cardX + cardW - bOff + 14, qrMidY + rows[i]);
    ctx.stroke();
    ctx.restore();
  }

  // Bottom branding
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = "#6366f1";
  ctx.font = "600 14px monospace";
  ctx.textAlign = "left";
  ctx.fillText("zynd.ai", 52, H - 52);
  ctx.fillStyle = "#94a3b8";
  ctx.font = "bold 10px monospace";
  ctx.textAlign = "right";
  ctx.fillText("ONE PROFILE.", W - 52, H - 68);
  ctx.fillText("MORE OPPORTUNITIES.", W - 52, H - 52);

  return new Promise((resolve) => {
    canvas.toBlob((blob) => resolve(blob), "image/png");
  });
}

// ── ShareQrGroup ─────────────────────────────────────────────────────────────

export function ShareQrGroup({
  url,
  name,
  handle,
  avatarUrl,
  resume,
  headline,
  alias,
}: {
  url: string;
  name: string;
  handle: string;
  avatarUrl?: string | null;
  resume?: ResumeData | null;
  headline?: string | null;
  alias?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<ShareTab>("link");
  const [copied, setCopied] = useState<string | null>(null);
  const [qrFull, setQrFull] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const svgRef = useRef<SVGSVGElement>(null);
  const cardSvgRef = useRef<SVGSVGElement>(null);
  const fullSvgRef = useRef<SVGSVGElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const siteOrigin = cardsSiteOrigin();
  const shareUrl = withShareRef(url, handle);
  const shortUrl = alias
    ? withShareRef(`${siteOrigin}/${alias}`, handle)
    : null;
  const displayHeadline = (headline || "").trim() || "Zynd Card";
  const ogPreview = `/p/${encodeURIComponent(handle)}/opengraph-image`;
  const badgeMd = `[![Zynd Card](${siteOrigin}/p/${encodeURIComponent(handle)}/badge.svg)](${shareUrl})`;
  const emailSigPlain = `${name}\n${displayHeadline}\n${shareUrl}`;
  const emailSigHtml = `<div style="font-family:sans-serif;font-size:13px;line-height:1.45;color:#0B0B0B"><strong>${escapeHtml(name)}</strong><br/>${escapeHtml(displayHeadline)}<br/><a href="${escapeHtml(shareUrl)}" style="color:#6157DE">${escapeHtml(shareUrl.replace(/^https?:\/\//, ""))}</a></div>`;
  const linkedinFeatured = `Add this to LinkedIn Featured:\n${shareUrl}`;

  const flashCopied = useCallback((key: string) => {
    setCopied(key);
    window.setTimeout(() => setCopied((cur) => (cur === key ? null : cur)), 2000);
  }, []);

  const trackShare = useCallback(
    (target?: string) => {
      track("share_click", { handle, ...(target ? { target } : {}) }, handle);
    },
    [handle],
  );

  const onCopy = useCallback(
    async (text: string, key: string, target?: string) => {
      await writeClipboard(text);
      trackShare(target);
      flashCopied(key);
    },
    [flashCopied, trackShare],
  );

  const onDownloadCard = useCallback(async () => {
    const svg = cardSvgRef.current ?? svgRef.current;
    if (!svg || downloading) return;
    setDownloading(true);
    try {
      const blob = await buildIdentityCard(svg, name, handle, avatarUrl);
      if (!blob) return;
      const a = document.createElement("a");
      const pngUrl = URL.createObjectURL(blob);
      a.href = pngUrl;
      a.download = `zynd-${handle}-identity.png`;
      a.click();
      URL.revokeObjectURL(pngUrl);
      trackShare("identity_card");
    } finally {
      setDownloading(false);
    }
  }, [name, handle, avatarUrl, downloading, trackShare]);

  const close = useCallback(() => {
    setOpen(false);
    setQrFull(false);
  }, []);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        if (qrFull) setQrFull(false);
        else close();
      }
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, qrFull, close]);

  const openShare = () => {
    setOpen(true);
    setTab("link");
    trackShare("sheet");
  };

  const pill =
    "inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full border border-[#DCDCD7] bg-white text-[12px]! font-mono font-medium transition-all shadow-sm group hover:bg-black hover:!text-white";

  return (
    <div className="relative flex items-stretch">
      <button
        type="button"
        onClick={openShare}
        aria-haspopup="dialog"
        aria-expanded={open}
        style={{ color: "#0B0B0B" }}
        className={pill}
        onMouseEnter={(e) => { e.currentTarget.style.color = "#fff"; }}
        onMouseLeave={(e) => { e.currentTarget.style.color = "#0B0B0B"; }}
      >
        <Share2 size={14} className="text-[#8E8E88] group-hover:!text-white transition-colors" />
        <span>Share</span>
      </button>

      {open && (
        <div
          style={{ position: "fixed", inset: 0, zIndex: 100, display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}
        >
          <div style={{ position: "absolute", inset: 0, background: "rgba(11,11,11,.34)" }} onClick={close} aria-hidden />
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            style={{
              position: "relative",
              width: "min(440px, 100%)",
              maxHeight: "min(720px, 100%)",
              display: "flex",
              flexDirection: "column",
              overflow: "hidden",
              background: "#F7F7F4",
              borderRadius: 28,
              boxShadow: "0 30px 80px rgba(11,11,11,.32)",
            }}
          >
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, padding: "20px 22px 14px", borderBottom: "1px solid #E4E4DE" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
                <div style={{ font: "700 10px/1 'Space Mono', ui-monospace, monospace", letterSpacing: ".14em", textTransform: "uppercase", color: "#8E8E88" }}>
                  Share profile
                </div>
                <div id={titleId} role="heading" aria-level={2} style={{ font: "700 22px/1.15 'Space Grotesk', sans-serif", color: "#0B0B0B", letterSpacing: "-.02em" }}>
                  {name}
                </div>
              </div>
              <button
                ref={closeRef}
                type="button"
                onClick={close}
                aria-label="Close"
                style={{ cursor: "pointer", width: 34, height: 34, borderRadius: 12, border: "1px solid #E4E4DE", background: "#fff", color: "#0B0B0B", display: "flex", alignItems: "center", justifyContent: "center" }}
              >
                <X size={16} />
              </button>
            </div>

            <div role="tablist" aria-label="Share options" style={{ display: "flex", gap: 4, padding: "10px 14px 0", overflowX: "auto" }}>
              {TABS.map((t) => {
                const active = tab === t.id;
                return (
                  <button
                    key={t.id}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    id={`share-tab-${t.id}`}
                    onClick={() => setTab(t.id)}
                    style={{
                      flex: "none",
                      cursor: "pointer",
                      padding: "8px 12px",
                      borderRadius: 999,
                      border: active ? "1px solid #0B0B0B" : "1px solid transparent",
                      background: active ? "#0B0B0B" : "transparent",
                      color: active ? "#fff" : "#6E6E68",
                      font: "600 11px/1 'Space Mono', ui-monospace, monospace",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {t.label}
                  </button>
                );
              })}
            </div>

            <div
              role="tabpanel"
              aria-labelledby={`share-tab-${tab}`}
              style={{ flex: 1, overflowY: "auto", padding: "16px 22px 22px" }}
            >
              {tab === "link" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                  <UnfurlPreview
                    name={name}
                    headline={displayHeadline}
                    avatarUrl={avatarUrl}
                    ogSrc={ogPreview}
                    urlLabel={(shortUrl || shareUrl).replace(/^https?:\/\//, "")}
                  />
                  <CopyRow
                    label="Profile link"
                    value={shareUrl}
                    copied={copied === "link"}
                    onCopy={() => onCopy(shareUrl, "link", "copy")}
                  />
                  {shortUrl && (
                    <CopyRow
                      label="Short alias"
                      value={shortUrl}
                      hint="Canonical SEO URL stays /p/…"
                      copied={copied === "alias"}
                      onCopy={() => onCopy(shortUrl, "alias", "alias")}
                    />
                  )}
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                    <TargetButton
                      label="LinkedIn"
                      onClick={() => {
                        trackShare("linkedin");
                        window.open(
                          `https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(shareUrl)}`,
                          "_blank",
                          "noopener,noreferrer",
                        );
                      }}
                    />
                    <TargetButton
                      label="X"
                      onClick={() => {
                        trackShare("x");
                        window.open(
                          `https://twitter.com/intent/tweet?url=${encodeURIComponent(shareUrl)}&text=${encodeURIComponent(name)}`,
                          "_blank",
                          "noopener,noreferrer",
                        );
                      }}
                    />
                    <TargetButton
                      label="WhatsApp"
                      onClick={() => {
                        trackShare("whatsapp");
                        window.open(
                          `https://wa.me/?text=${encodeURIComponent(`${name} — ${shareUrl}`)}`,
                          "_blank",
                          "noopener,noreferrer",
                        );
                      }}
                    />
                    <TargetButton
                      label="Email"
                      icon={<Mail size={13} />}
                      onClick={() => {
                        trackShare("email");
                        window.location.href = `mailto:?subject=${encodeURIComponent(name)}&body=${encodeURIComponent(shareUrl)}`;
                      }}
                    />
                  </div>
                </div>
              )}

              {tab === "qr" && (
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
                  <div style={{ borderRadius: 16, overflow: "hidden", border: "1px solid #F0F0EA", padding: 12, background: "#fff", lineHeight: 0 }}>
                    <QRCodeSVG
                      ref={svgRef}
                      value={shareUrl}
                      size={272}
                      fgColor="#0B0B0B"
                      bgColor="#ffffff"
                      level="M"
                      marginSize={4}
                      style={{ width: "min(272px, 66vw)", height: "min(272px, 66vw)" }}
                    />
                  </div>
                  <span style={{ font: "400 10px/1.4 'Space Mono', ui-monospace, monospace", color: "#8E8E88", textAlign: "center", wordBreak: "break-all", maxWidth: 280 }}>
                    {shareUrl.replace(/^https?:\/\//, "")}
                  </span>
                  <span style={{ font: "700 9px/1 'Space Mono', ui-monospace, monospace", letterSpacing: ".14em", textTransform: "uppercase", color: "#7B72E9" }}>
                    Scan to view profile
                  </span>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
                    <ActionChip onClick={() => setQrFull(true)} icon={<Maximize2 size={12} />}>Fullscreen</ActionChip>
                    <ActionChip onClick={() => { downloadQrSvg(svgRef.current); trackShare("qr_svg"); }} icon={<Download size={12} />}>SVG</ActionChip>
                    <ActionChip onClick={() => { void downloadQrPng(svgRef.current, handle); trackShare("qr_png"); }} icon={<Download size={12} />}>PNG</ActionChip>
                  </div>
                </div>
              )}

              {tab === "card" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                  <p style={{ margin: 0, font: "400 13px/1.5 sans-serif", color: "#6E6E68" }}>
                    Offline / print PNG with your QR. Distinct from the link unfurl image.
                  </p>
                  <div aria-hidden style={{ position: "absolute", width: 0, height: 0, overflow: "hidden" }}>
                    <QRCodeSVG ref={cardSvgRef} value={shareUrl} size={272} fgColor="#0B0B0B" bgColor="#ffffff" level="M" marginSize={4} />
                  </div>
                  <button
                    type="button"
                    onClick={onDownloadCard}
                    disabled={downloading}
                    style={{
                      cursor: downloading ? "wait" : "pointer",
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: 8,
                      padding: "12px 16px",
                      borderRadius: 999,
                      border: "none",
                      background: "#0B0B0B",
                      color: "#fff",
                      font: "600 12px/1 'Space Mono', ui-monospace, monospace",
                      opacity: downloading ? 0.6 : 1,
                    }}
                  >
                    <Download size={14} />
                    {downloading ? "Building…" : "Download Identity Card"}
                  </button>
                  <button
                    type="button"
                    onClick={() => { if (resume) { setPickerOpen(true); trackShare("resume"); } }}
                    disabled={!resume}
                    style={{
                      cursor: resume ? "pointer" : "not-allowed",
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: 8,
                      padding: "12px 16px",
                      borderRadius: 999,
                      border: "1px solid #E4E4DE",
                      background: "#fff",
                      color: "#0B0B0B",
                      font: "600 12px/1 'Space Mono', ui-monospace, monospace",
                      opacity: resume ? 1 : 0.5,
                    }}
                  >
                    <FileText size={14} />
                    Download Resume
                  </button>
                </div>
              )}

              {tab === "embed" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                  <CopyBlock
                    title="Email signature (plain)"
                    value={emailSigPlain}
                    copied={copied === "sig-plain"}
                    onCopy={() => onCopy(emailSigPlain, "sig-plain", "email_sig")}
                  />
                  <CopyBlock
                    title="Email signature (HTML)"
                    value={emailSigHtml}
                    copied={copied === "sig-html"}
                    onCopy={() => onCopy(emailSigHtml, "sig-html", "email_sig_html")}
                  />
                  <CopyBlock
                    title="LinkedIn Featured"
                    value={linkedinFeatured}
                    copied={copied === "li-featured"}
                    onCopy={() => onCopy(linkedinFeatured, "li-featured", "linkedin_featured")}
                  />
                  <CopyBlock
                    title="README badge"
                    value={badgeMd}
                    copied={copied === "badge"}
                    onCopy={() => onCopy(badgeMd, "badge", "readme_badge")}
                  />
                  <a
                    href={`/p/${encodeURIComponent(handle)}/vcard`}
                    onClick={() => trackShare("vcard")}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: 8,
                      padding: "12px 16px",
                      borderRadius: 999,
                      border: "1px solid #E4E4DE",
                      background: "#fff",
                      color: "#0B0B0B",
                      font: "600 12px/1 'Space Mono', ui-monospace, monospace",
                      textDecoration: "none",
                    }}
                  >
                    <Download size={14} />
                    Download vCard
                  </a>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {qrFull && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="QR code"
          className="fixed inset-0 z-[110] flex items-center justify-center bg-black/85 p-4"
          onClick={() => setQrFull(false)}
        >
          <div className="flex flex-col items-center gap-4" onClick={(e) => e.stopPropagation()}>
            <div className="rounded-2xl bg-white p-5 leading-none" style={{ maxWidth: "90vw" }}>
              <QRCodeSVG
                ref={fullSvgRef}
                value={shareUrl}
                size={320}
                fgColor="#0B0B0B"
                bgColor="#ffffff"
                level="Q"
                marginSize={4}
                style={{ width: "min(320px, 76vw)", height: "min(320px, 76vw)" }}
              />
            </div>
            <div className="flex items-center gap-2">
              <button type="button" onClick={() => downloadQrSvg(fullSvgRef.current)} className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full bg-white text-black hover:bg-[#eee] transition-colors font-mono text-[11px]! font-semibold">
                <Download size={13} /> SVG
              </button>
              <button type="button" onClick={() => downloadQrPng(fullSvgRef.current, handle)} className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full bg-white text-black hover:bg-[#eee] transition-colors font-mono text-[11px]! font-semibold">
                <Download size={13} /> PNG
              </button>
              <button type="button" onClick={() => setQrFull(false)} className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full bg-white/10 text-white border border-white/25 hover:bg-white/20 transition-colors font-mono text-[11px]! font-semibold">
                <X size={13} /> Close
              </button>
            </div>
          </div>
        </div>
      )}

      {pickerOpen && resume && (
        <ResumePicker resume={resume} handle={handle} onClose={() => setPickerOpen(false)} />
      )}
    </div>
  );
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function UnfurlPreview({
  name,
  headline,
  avatarUrl,
  ogSrc,
  urlLabel,
}: {
  name: string;
  headline: string;
  avatarUrl?: string | null;
  ogSrc: string;
  urlLabel: string;
}) {
  return (
    <div style={{ border: "1px solid #E4E4DE", borderRadius: 16, overflow: "hidden", background: "#fff" }}>
      <div style={{ height: 120, background: "linear-gradient(120deg,#1e1b4b,#4f46e5)", position: "relative" }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={ogSrc} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </div>
      <div style={{ display: "flex", gap: 10, padding: 12, alignItems: "center" }}>
        {avatarUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={avatarUrl} alt="" width={40} height={40} style={{ borderRadius: 10, objectFit: "cover" }} />
        ) : (
          <div style={{ width: 40, height: 40, borderRadius: 10, background: "#EDEBFD", color: "#6157DE", display: "flex", alignItems: "center", justifyContent: "center", font: "700 14px/1 sans-serif" }}>
            {name.slice(0, 1).toUpperCase()}
          </div>
        )}
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ font: "700 13px/1.2 sans-serif", color: "#0B0B0B", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name}</div>
          <div style={{ font: "400 12px/1.3 sans-serif", color: "#6E6E68", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{headline}</div>
          <div style={{ font: "400 10px/1.3 'Space Mono', ui-monospace, monospace", color: "#8E8E88", marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{urlLabel}</div>
        </div>
      </div>
    </div>
  );
}

function CopyRow({
  label,
  value,
  hint,
  copied,
  onCopy,
}: {
  label: string;
  value: string;
  hint?: string;
  copied: boolean;
  onCopy: () => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
        <span style={{ font: "700 10px/1 'Space Mono', ui-monospace, monospace", letterSpacing: ".12em", textTransform: "uppercase", color: "#8E8E88" }}>{label}</span>
        {hint && <span style={{ font: "400 10px/1 sans-serif", color: "#A8A8A2" }}>{hint}</span>}
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <code style={{ flex: 1, minWidth: 0, padding: "10px 12px", borderRadius: 12, background: "#fff", border: "1px solid #E4E4DE", font: "400 11px/1.3 'Space Mono', ui-monospace, monospace", color: "#0B0B0B", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {value.replace(/^https?:\/\//, "")}
        </code>
        <button
          type="button"
          onClick={onCopy}
          style={{
            cursor: "pointer",
            flex: "none",
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "10px 12px",
            borderRadius: 12,
            border: "none",
            background: copied ? "#10b981" : "#0B0B0B",
            color: "#fff",
            font: "600 11px/1 'Space Mono', ui-monospace, monospace",
          }}
        >
          {copied ? <Check size={13} /> : <Copy size={13} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}

function CopyBlock({
  title,
  value,
  copied,
  onCopy,
}: {
  title: string;
  value: string;
  copied: boolean;
  onCopy: () => void;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <span style={{ font: "700 10px/1 'Space Mono', ui-monospace, monospace", letterSpacing: ".12em", textTransform: "uppercase", color: "#8E8E88" }}>{title}</span>
        <button
          type="button"
          onClick={onCopy}
          style={{
            cursor: "pointer",
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            padding: "6px 10px",
            borderRadius: 999,
            border: "1px solid #E4E4DE",
            background: copied ? "#10b981" : "#fff",
            color: copied ? "#fff" : "#0B0B0B",
            font: "600 10px/1 'Space Mono', ui-monospace, monospace",
          }}
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre style={{ margin: 0, padding: 12, borderRadius: 12, background: "#fff", border: "1px solid #E4E4DE", font: "400 11px/1.45 'Space Mono', ui-monospace, monospace", color: "#0B0B0B", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: 110, overflow: "auto" }}>
        {value}
      </pre>
    </div>
  );
}

function TargetButton({
  label,
  onClick,
  icon,
}: {
  label: string;
  onClick: () => void;
  icon?: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        cursor: "pointer",
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
        padding: "11px 10px",
        borderRadius: 14,
        border: "1px solid #E4E4DE",
        background: "#fff",
        color: "#0B0B0B",
        font: "600 11px/1 'Space Mono', ui-monospace, monospace",
      }}
    >
      {icon ?? <Share2 size={13} />}
      {label}
    </button>
  );
}

function ActionChip({
  children,
  onClick,
  icon,
}: {
  children: React.ReactNode;
  onClick: () => void;
  icon: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        cursor: "pointer",
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "8px 12px",
        borderRadius: 999,
        border: "1px solid #E4E4DE",
        background: "#fff",
        color: "#0B0B0B",
        font: "600 10px/1 'Space Mono', ui-monospace, monospace",
      }}
    >
      {icon}
      {children}
    </button>
  );
}

// ── Standalone buttons ───────────────────────────────────────────────────────

async function writeClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = "position:fixed;opacity:0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
  }
}

function downloadQrSvg(svg: SVGSVGElement | null) {
  if (!svg) return;
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute("width", "640");
  clone.setAttribute("height", "640");
  const blob = new Blob([new XMLSerializer().serializeToString(clone)], { type: "image/svg+xml" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "zynd-qr.svg";
  a.click();
  URL.revokeObjectURL(a.href);
}

async function downloadQrPng(svg: SVGSVGElement | null, handle: string) {
  if (!svg) return;
  const svgText = new XMLSerializer().serializeToString(svg);
  const blob = new Blob([svgText], { type: "image/svg+xml" });
  const url = URL.createObjectURL(blob);
  try {
    const img = new Image();
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error("svg load failed"));
      img.src = url;
    });
    const canvas = document.createElement("canvas");
    canvas.width = 1280;
    canvas.height = 1280;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    const png = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!png) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(png);
    a.download = `zynd-${handle}-qr.png`;
    a.click();
    URL.revokeObjectURL(a.href);
  } catch {
    // best-effort export
  } finally {
    URL.revokeObjectURL(url);
  }
}

export function ShareButton({ url, handle }: { url: string; handle?: string }) {
  const [copied, setCopied] = useState(false);

  const onClick = useCallback(async () => {
    await writeClipboard(url);
    if (handle) track("share_click", { handle }, handle);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [url, handle]);

  return (
    <>
      <button
        type="button"
        onClick={onClick}
        style={{ color: "#0B0B0B" }}
        className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-white hover:bg-black hover:!text-white border border-[#DCDCD7] text-[12px]! font-mono font-medium transition-all shadow-sm group"
      >
        <Link2 size={15} className="text-[#8E8E88] group-hover:text-white transition-colors" />
        <span>Share</span>
      </button>
      <span className={`transition-opacity duration-300 font-mono text-[11px] text-emerald-600 font-semibold ${copied ? "opacity-100" : "opacity-0"}`}>
        Copied!
      </span>
    </>
  );
}

export function CopyPermalinkIcon({ url, handle }: { url: string; handle?: string }) {
  const [copied, setCopied] = useState(false);

  const onClick = useCallback(async () => {
    await writeClipboard(url);
    if (handle) track("share_click", { handle }, handle);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [url, handle]);

  return (
    <button
      type="button"
      onClick={onClick}
      className={`p-1.5 rounded-xl transition-colors cursor-pointer ${copied ? "bg-black text-white" : "hover:bg-black hover:text-white text-[#8E8E88]"}`}
      title={copied ? "Copied!" : "Copy profile link"}
      aria-label={copied ? "Copied" : "Copy profile link"}
    >
      {copied ? <Check size={16} /> : <Copy size={16} />}
    </button>
  );
}

export function QrButton({ url, handle }: { url: string; handle?: string }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => {
          if (!open && handle) track("share_click", { handle }, handle);
          setOpen((v) => !v);
        }}
        aria-expanded={open}
        aria-label="Show QR code"
        style={{ color: "#0B0B0B" }}
        className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-full bg-white hover:bg-black hover:!text-white border border-[#DCDCD7] text-[12px]! font-mono font-medium transition-all shadow-sm group"
      >
        <QrCode size={15} className="text-[#8E8E88] group-hover:text-white transition-colors" />
        <span>QR</span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} aria-hidden />
          <div className="absolute right-0 top-full mt-2 z-50 bg-white border border-[#E5E5DE] rounded-2xl shadow-xl p-4 flex flex-col items-center gap-2.5">
            <div className="rounded-xl overflow-hidden border border-[#F0F0EA] p-3 bg-white leading-none">
              <QRCodeSVG
                value={url}
                size={272}
                fgColor="#0B0B0B"
                bgColor="#ffffff"
                level="M"
                marginSize={4}
                style={{ width: "min(272px, 66vw)", height: "min(272px, 66vw)" }}
              />
            </div>
            <span className="font-mono text-[10px] text-[#8E8E88] break-all max-w-[280px] text-center leading-snug">
              {url.replace(/^https?:\/\//, "")}
            </span>
            <span className="font-mono text-[9px] uppercase tracking-widest text-[#7B72E9] font-bold">
              Scan to view profile
            </span>
          </div>
        </>
      )}
    </div>
  );
}
