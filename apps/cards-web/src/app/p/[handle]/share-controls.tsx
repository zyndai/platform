"use client";

import { useCallback, useRef, useState } from "react";
import { Check, ChevronDown, Copy, Download, FileText, Link2, QrCode, Share2 } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";

import { ResumePicker } from "./resume-picker";
import type { ResumeData } from "./resume-pdf";

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
}: {
  url: string;
  name: string;
  handle: string;
  avatarUrl?: string | null;
  resume?: ResumeData | null;
}) {
  const [copied, setCopied] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [qrOpen, setQrOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const svgRef = useRef<SVGSVGElement>(null);

  const onCopyLink = useCallback(async () => {
    await writeClipboard(url);
    setCopied(true);
    setMenuOpen(false);
    setTimeout(() => setCopied(false), 2000);
  }, [url]);

  const onDownloadResume = useCallback(() => {
    if (!resume) return;
    setMenuOpen(false);
    setPickerOpen(true);
  }, [resume]);

  const onDownload = useCallback(async () => {
    const svg = svgRef.current;
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
    } finally {
      setDownloading(false);
    }
  }, [name, handle, avatarUrl, downloading]);

  // Inline color, not a utility class: globals.css is unlayered and outranks
  // `@layer utilities`, which is why every button on this page sets it this way.
  const menuItem =
    "flex w-full items-center gap-2.5 px-3 py-2 text-left font-mono text-[11px]! font-medium hover:bg-[#F5F5F0] transition-colors disabled:opacity-50 disabled:hover:bg-transparent";
  const menuItemStyle = { color: "#0B0B0B" } as const;

  return (
    <div className="relative flex items-stretch">
      <div className="inline-flex items-stretch rounded-full border border-[#DCDCD7] bg-white shadow-sm overflow-hidden">
        {/* Export / Share half */}
        <button
          type="button"
          onClick={() => { setMenuOpen((v) => !v); setQrOpen(false); }}
          aria-expanded={menuOpen}
          aria-haspopup="menu"
          style={{ color: copied || menuOpen ? "#fff" : "#0B0B0B" }}
          className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 text-[12px]! font-mono font-medium transition-all group
            ${copied ? "bg-emerald-500 hover:!text-white" : menuOpen ? "bg-black hover:!text-white" : "hover:bg-black hover:!text-white"}`}
          onMouseEnter={(e) => { if (!copied) e.currentTarget.style.color = "#fff"; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = copied || menuOpen ? "#fff" : "#0B0B0B"; }}
        >
          {copied ? (
            <Check size={14} />
          ) : (
            <Share2 size={14} className={`transition-colors ${menuOpen ? "text-white" : "text-[#8E8E88] group-hover:!text-white"}`} />
          )}
          <span>{copied ? "Copied!" : "Export / Share"}</span>
          {!copied && (
            <ChevronDown
              size={12}
              className={`transition-transform ${menuOpen ? "text-white rotate-180" : "text-[#8E8E88] group-hover:!text-white"}`}
            />
          )}
        </button>

        <span className="w-px bg-[#DCDCD7] self-stretch" />

        {/* QR half */}
        <button
          type="button"
          onClick={() => { setQrOpen((v) => !v); setMenuOpen(false); setCopied(false); }}
          aria-expanded={qrOpen}
          aria-label="Show QR code"
          style={{ color: qrOpen ? "#fff" : "#0B0B0B" }}
          className={`inline-flex items-center gap-1.5 px-3.5 py-1.5 text-[12px]! font-mono font-medium transition-all group
            ${qrOpen ? "bg-black hover:!text-white" : "hover:bg-black hover:!text-white"}`}
          onMouseEnter={(e) => { e.currentTarget.style.color = "#fff"; }}
          onMouseLeave={(e) => { e.currentTarget.style.color = qrOpen ? "#fff" : "#0B0B0B"; }}
        >
          <QrCode size={14} className={`transition-colors ${qrOpen ? "text-white" : "text-[#8E8E88] group-hover:!text-white"}`} />
          <span>QR</span>
        </button>
      </div>

      {/* Export / Share menu */}
      {menuOpen && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setMenuOpen(false)} aria-hidden />
          <div
            role="menu"
            className="absolute left-0 top-full mt-2 z-50 min-w-[196px] bg-white border border-[#E5E5DE] rounded-2xl shadow-xl py-1.5 overflow-hidden"
          >
            <button type="button" role="menuitem" onClick={onDownloadResume} disabled={!resume} className={menuItem} style={menuItemStyle}>
              <FileText size={14} style={{ color: "#8E8E88" }} />
              <span>Download Resume</span>
            </button>
            <button type="button" role="menuitem" onClick={onCopyLink} className={menuItem} style={menuItemStyle}>
              <Link2 size={14} style={{ color: "#8E8E88" }} />
              <span>Copy Link</span>
            </button>
          </div>
        </>
      )}

      {/* QR popover */}
      {qrOpen && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setQrOpen(false)} aria-hidden />
          <div className="absolute right-0 top-full mt-2 z-50 bg-white border border-[#E5E5DE] rounded-2xl shadow-xl p-4 flex flex-col items-center gap-2.5">
            <div className="rounded-xl overflow-hidden border border-[#F0F0EA] p-2.5 bg-white leading-none">
              <QRCodeSVG ref={svgRef} value={url} size={136} fgColor="#0B0B0B" bgColor="#ffffff" level="M" marginSize={0} />
            </div>
            <span className="font-mono text-[10px] text-[#8E8E88] break-all max-w-[170px] text-center leading-snug">
              {url.replace(/^https?:\/\//, "")}
            </span>
            <span className="font-mono text-[9px] uppercase tracking-widest text-[#7B72E9] font-bold">
              Scan to view profile
            </span>
            <button
              type="button"
              onClick={onDownload}
              disabled={downloading}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-black text-white hover:bg-[#333] transition-colors font-mono text-[10px]! font-semibold mt-0.5 disabled:opacity-60"
            >
              <Download size={12} />
              {downloading ? "Building…" : "Download Identity Card"}
            </button>
          </div>
        </>
      )}

      {pickerOpen && resume && (
        <ResumePicker resume={resume} handle={handle} onClose={() => setPickerOpen(false)} />
      )}
    </div>
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

export function ShareButton({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);

  const onClick = useCallback(async () => {
    await writeClipboard(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [url]);

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

export function CopyPermalinkIcon({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);

  const onClick = useCallback(async () => {
    await writeClipboard(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [url]);

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

export function QrButton({ url }: { url: string }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
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
            <div className="rounded-xl overflow-hidden border border-[#F0F0EA] p-2.5 bg-white leading-none">
              <QRCodeSVG value={url} size={136} fgColor="#0B0B0B" bgColor="#ffffff" level="M" marginSize={0} />
            </div>
            <span className="font-mono text-[10px] text-[#8E8E88] break-all max-w-[170px] text-center leading-snug">
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
