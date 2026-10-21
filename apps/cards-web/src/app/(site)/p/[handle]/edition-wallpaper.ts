/* "QR wallpaper": a phone lock-screen image that works like an event pass:
 * who the owner is and a large QR of their card on a ticket, with the Mumbai
 * skyline along the bottom. Drawn in the browser from the same SVGs the QR
 * screen renders, in a light and a dark version. */

/** 1170 x 2532 is the iPhone 12-16 screen; other phones crop the sides a little. */
export const WALLPAPER_W = 1170;
export const WALLPAPER_H = 2532;

export type WallpaperTheme = "light" | "dark";

export interface WallpaperInput {
  theme: WallpaperTheme;
  /** The skyline in that theme, drawn without a sky (MumbaiSkyline `silhouette`). */
  art: SVGSVGElement;
  qr: SVGSVGElement;
  avatarSrc: string | null;
  initials: string;
  name: string;
  headline: string;
  hereFor: string | null;
  permalink: string;
  /** Resolved CSS font stacks for the edition's UI and mono faces. */
  fonts: { ui: string; mono: string };
}

const THEMES = {
  light: {
    background: ["#E7E2FD", "#F6F3FF", "#ECE6FC"],
    ticket: "#FFFFFF", ticketEdge: "#E2DCFB", shadow: "rgba(30,27,75,0.18)",
    ink: "#1E1B4B", soft: "#5B5B7E", eyebrow: "#4C3FC9", rule: "#E6E1FA",
    chip: "#6C5CE7", stars: null as string | null,
  },
  dark: {
    background: ["#08071F", "#141139", "#231F5C"],
    ticket: "#17143D", ticketEdge: "rgba(255,255,255,0.12)", shadow: "rgba(0,0,0,0.45)",
    ink: "#FFFFFF", soft: "#C9C4F5", eyebrow: "#B9AEFF", rule: "rgba(255,255,255,0.16)",
    chip: "#8B7CF6", stars: "#FFFFFF" as string | null,
  },
} as const;

// Official Ethereum mark geometry (256 x 417), as in components/editions/eth-mark.tsx.
const ETH_FACES: [string, string][] = [
  ["#4B3FC9", "m127.961 0-2.795 9.5v275.668l2.795 2.79 127.962-75.638z"],
  ["#8F86F2", "M127.962 0 0 212.32l127.962 75.639V154.158z"],
  ["#5A4FD6", "m127.961 312.187-1.575 1.92v98.199l1.575 4.601 128.038-180.32z"],
  ["#8F86F2", "M127.962 416.905v-104.72L0 236.585z"],
  ["#2E2499", "m127.961 287.958 127.96-75.637-127.96-58.162z"],
  ["#6C62E0", "m0 212.32 127.96 75.638v-133.8z"],
];

function svgToImage(svg: SVGSVGElement, width: number, height: number): Promise<HTMLImageElement> {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], { type: "image/svg+xml;charset=utf-8" }));
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("wallpaper: could not rasterize SVG"));
    img.src = url;
  }).finally(() => URL.revokeObjectURL(url));
}

function loadPhoto(src: string): Promise<HTMLImageElement | null> {
  // Same-origin /api/img proxy, so the canvas stays exportable. A missing
  // photo falls back to initials rather than failing the whole wallpaper.
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

// Drawn with arcTo rather than ctx.roundRect, which iOS Safari only has from 16.
function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/** Largest size (down to `min`) at which `text` fits in `maxWidth`; leaves ctx.font set. */
function fitFont(ctx: CanvasRenderingContext2D, text: string, weight: number, family: string, size: number, min: number, maxWidth: number): number {
  let s = size;
  ctx.font = `${weight} ${s}px ${family}`;
  while (s > min && ctx.measureText(text).width > maxWidth) {
    s -= 2;
    ctx.font = `${weight} ${s}px ${family}`;
  }
  return s;
}

function ellipsize(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let t = text;
  while (t.length > 1 && ctx.measureText(`${t}…`).width > maxWidth) t = t.slice(0, -1);
  return `${t.trimEnd()}…`;
}

function drawEthMark(ctx: CanvasRenderingContext2D, x: number, y: number, height: number) {
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(height / 417, height / 417);
  for (const [fill, d] of ETH_FACES) {
    ctx.fillStyle = fill;
    ctx.fill(new Path2D(d));
  }
  ctx.restore();
}

/** A prism crystal like the banner's, for the empty sky around the clock. */
function drawCrystal(ctx: CanvasRenderingContext2D, x: number, y: number, s: number, dark: boolean) {
  const top = -s * 1.55;
  const bottom = s * 1.7;
  const belt = s * 0.18;
  const faces: [string, string][] = dark
    ? [["#8F86F2", `M0,${top} L${-s},0 L0,${belt}Z`], ["#6C62E0", `M0,${top} L${s},0 L0,${belt}Z`], ["#4B3FC9", `M${-s},0 L0,${bottom} L0,${belt}Z`], ["#2E2499", `M${s},0 L0,${bottom} L0,${belt}Z`]]
    : [["#FFFFFF", `M0,${top} L${-s},0 L0,${belt}Z`], ["#C9C2FA", `M0,${top} L${s},0 L0,${belt}Z`], ["#B4ACF6", `M${-s},0 L0,${bottom} L0,${belt}Z`], ["#8C82EC", `M${s},0 L0,${bottom} L0,${belt}Z`]];
  ctx.save();
  ctx.translate(x, y);
  const glow = ctx.createRadialGradient(0, 0, 0, 0, 0, s * 2.4);
  glow.addColorStop(0, dark ? "rgba(139,124,246,0.35)" : "rgba(255,255,255,0.75)");
  glow.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = glow;
  ctx.beginPath();
  ctx.arc(0, 0, s * 2.4, 0, Math.PI * 2);
  ctx.fill();
  for (const [fill, d] of faces) {
    ctx.fillStyle = fill;
    ctx.fill(new Path2D(d));
  }
  ctx.restore();
}

export async function renderWallpaper(input: WallpaperInput): Promise<Blob> {
  const { fonts } = input;
  const t = THEMES[input.theme];
  const dark = input.theme === "dark";
  await Promise.all([
    document.fonts.load(`800 60px ${fonts.ui}`),
    document.fonts.load(`500 30px ${fonts.ui}`),
    document.fonts.load(`700 30px ${fonts.mono}`),
  ]);

  const W = WALLPAPER_W;
  const H = WALLPAPER_H;
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("wallpaper: 2D canvas unavailable");

  // The skyline footer. The art is 1600 x 500; the silhouette's city starts
  // around y = 150, so the crop drawn here is that lower 350.
  const ART_W = 1500;
  const ART_H = Math.round((ART_W / 1600) * 350);
  const [art, qr, photo] = await Promise.all([
    svgToImage(input.art, ART_W, ART_H),
    svgToImage(input.qr, 800, 800),
    input.avatarSrc ? loadPhoto(input.avatarSrc) : Promise.resolve(null),
  ]);

  const bg = ctx.createLinearGradient(0, 0, 0, H);
  bg.addColorStop(0, t.background[0]);
  bg.addColorStop(0.55, t.background[1]);
  bg.addColorStop(1, t.background[2]);
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);

  // Sky around the lock-screen clock: the top ~30% is left free for it.
  if (t.stars) {
    let seed = 11;
    const next = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    ctx.fillStyle = t.stars;
    for (let i = 0; i < 90; i++) {
      ctx.globalAlpha = 0.25 + next() * 0.6;
      ctx.beginPath();
      ctx.arc(next() * W, next() * 900, 0.8 + next() * 2.2, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }
  drawCrystal(ctx, 150, 560, 30, dark);
  drawCrystal(ctx, 1030, 470, 40, dark);
  drawCrystal(ctx, 1085, 680, 18, dark);

  ctx.drawImage(art, (W - ART_W) / 2, H - ART_H, ART_W, ART_H);

  // ── The pass ──────────────────────────────────────────────────────────────
  const tx = 75;
  const tw = W - tx * 2;
  const pad = 60;
  const top = 790;
  const qrSize = 800;
  const headerH = 96;
  const idTop = top + headerH;
  const idH = input.hereFor ? 240 : 196;
  const stubY = idTop + idH;              // perforation between "who" and the QR
  const qrTop = stubY + 66;
  const footY = qrTop + qrSize + 34;
  const bottom = footY + 136;

  // Drawn on its own layer so the notches at the perforation can be cut out.
  const pass = document.createElement("canvas");
  pass.width = W;
  pass.height = H;
  const p = pass.getContext("2d");
  if (!p) throw new Error("wallpaper: 2D canvas unavailable");
  roundRect(p, tx, top, tw, bottom - top, 56);
  p.fillStyle = t.ticket;
  p.fill();
  p.lineWidth = 2;
  p.strokeStyle = t.ticketEdge;
  p.stroke();
  p.globalCompositeOperation = "destination-out";
  for (const cx of [tx, tx + tw]) {
    p.beginPath();
    p.arc(cx, stubY, 30, 0, Math.PI * 2);
    p.fill();
  }
  p.globalCompositeOperation = "source-over";

  ctx.save();
  ctx.shadowColor = t.shadow;
  ctx.shadowBlur = 70;
  ctx.shadowOffsetY = 30;
  ctx.drawImage(pass, 0, 0);
  ctx.restore();

  // Header: the edition, then a rule.
  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "left";
  ctx.font = `700 30px ${fonts.mono}`;
  const eyebrow = "MUMBAI BUILDER WEEK ’26";
  const eyebrowW = ctx.measureText(eyebrow).width + 44;
  const ex = W / 2 - eyebrowW / 2;
  drawEthMark(ctx, ex, top + 30, 38);
  ctx.fillStyle = t.eyebrow;
  ctx.fillText(eyebrow, ex + 44, top + 60);
  ctx.fillStyle = t.rule;
  ctx.fillRect(tx + pad, top + headerH - 1, tw - pad * 2, 2);

  // Who: photo, name, headline, here-for.
  const avatar = 132;
  const ax = tx + pad;
  const ay = idTop + 40;
  ctx.save();
  roundRect(ctx, ax, ay, avatar, avatar, 32);
  ctx.clip();
  if (photo) {
    const side = Math.min(photo.naturalWidth, photo.naturalHeight);
    ctx.drawImage(photo, (photo.naturalWidth - side) / 2, (photo.naturalHeight - side) / 2, side, side, ax, ay, avatar, avatar);
  } else {
    ctx.fillStyle = "#6C5CE7";
    ctx.fillRect(ax, ay, avatar, avatar);
    ctx.fillStyle = "#FFFFFF";
    ctx.font = `800 54px ${fonts.ui}`;
    ctx.textAlign = "center";
    ctx.fillText(input.initials, ax + avatar / 2, ay + avatar / 2 + 19);
    ctx.textAlign = "left";
  }
  ctx.restore();

  const textX = ax + avatar + 36;
  const textW = tx + tw - pad - textX;
  ctx.fillStyle = t.ink;
  fitFont(ctx, input.name, 800, fonts.ui, 60, 38, textW);
  ctx.fillText(ellipsize(ctx, input.name, textW), textX, ay + 58);
  if (input.headline) {
    ctx.font = `500 30px ${fonts.ui}`;
    ctx.fillStyle = t.soft;
    ctx.fillText(ellipsize(ctx, input.headline, textW), textX, ay + 106);
  }
  if (input.hereFor) {
    const label = `Here for · ${input.hereFor}`;
    ctx.font = `700 30px ${fonts.ui}`;
    const chipW = ctx.measureText(label).width + 56;
    roundRect(ctx, textX, ay + 132, chipW, 58, 29);
    ctx.fillStyle = t.chip;
    ctx.fill();
    ctx.fillStyle = "#FFFFFF";
    ctx.fillText(label, textX + 28, ay + 171);
  }

  // Perforation.
  ctx.save();
  ctx.strokeStyle = t.rule;
  ctx.lineWidth = 3;
  ctx.setLineDash([14, 14]);
  ctx.beginPath();
  ctx.moveTo(tx + 44, stubY);
  ctx.lineTo(tx + tw - 44, stubY);
  ctx.stroke();
  ctx.restore();

  // The QR on plain white with its quiet zone: dark modules on white scan best,
  // so the dark pass keeps a white plate too.
  const qx = W / 2 - qrSize / 2;
  roundRect(ctx, qx - 24, qrTop - 24, qrSize + 48, qrSize + 48, 36);
  ctx.fillStyle = "#FFFFFF";
  ctx.fill();
  ctx.drawImage(qr, qx, qrTop, qrSize, qrSize);

  // Footer: the link people can type if a scan fails.
  ctx.textAlign = "center";
  ctx.fillStyle = t.ink;
  fitFont(ctx, input.permalink, 700, fonts.mono, 36, 24, tw - pad * 2);
  ctx.fillText(input.permalink, W / 2, footY + 58);
  ctx.font = `500 26px ${fonts.ui}`;
  ctx.fillStyle = t.soft;
  ctx.fillText("Scan to open my Zynd card", W / 2, footY + 96);

  const png = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!png) throw new Error("wallpaper: canvas export returned no image");
  return png;
}

/** Phones get the share sheet ("Save Image" puts it in Photos); desktops get a download. */
export async function saveWallpaper(png: Blob, filename: string): Promise<"shared" | "downloaded" | "cancelled"> {
  const file = new File([png], filename, { type: "image/png" });
  const isTouch = window.matchMedia("(pointer: coarse)").matches;
  if (isTouch && navigator.canShare?.({ files: [file] })) {
    try {
      await navigator.share({ files: [file] });
      return "shared";
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return "cancelled";
      console.warn("wallpaper: share sheet failed, downloading instead", err);
    }
  }
  const url = URL.createObjectURL(png);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  // Safari starts the download asynchronously; revoking at once can cancel it.
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
  return "downloaded";
}
