/* "QR wallpaper": a phone lock-screen image with the edition artwork, who the
 * owner is and their card's QR, so a builder can show it without opening the
 * site. Drawn in the browser from the same SVGs the QR screen shows. */

/** 1170 x 2532 is the iPhone 12-15 screen; other phones crop the sides a little. */
export const WALLPAPER_W = 1170;
export const WALLPAPER_H = 2532;

export interface WallpaperInput {
  scene: SVGSVGElement;
  /** Sky colour the art is extended with above its top edge. */
  edges: { sky: string; water: string };
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

function svgToImage(svg: SVGSVGElement, width: number, height: number): Promise<HTMLImageElement> {
  const clone = svg.cloneNode(true) as SVGSVGElement;
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

/** Largest size (down to `min`) at which `text` fits in `maxWidth`. */
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

// Official Ethereum mark geometry (256 x 417), as in components/editions/eth-mark.tsx.
const ETH_FACES: [string, string][] = [
  ["#4B3FC9", "m127.961 0-2.795 9.5v275.668l2.795 2.79 127.962-75.638z"],
  ["#8F86F2", "M127.962 0 0 212.32l127.962 75.639V154.158z"],
  ["#5A4FD6", "m127.961 312.187-1.575 1.92v98.199l1.575 4.601 128.038-180.32z"],
  ["#8F86F2", "M127.962 416.905v-104.72L0 236.585z"],
  ["#2E2499", "m127.961 287.958 127.96-75.637-127.96-58.162z"],
  ["#6C62E0", "m0 212.32 127.96 75.638v-133.8z"],
];

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

const INK = "#1E1B4B";
const SOFT = "#5B5B7E";
const PAGE = "#F3F1FB";

export async function renderWallpaper(input: WallpaperInput): Promise<Blob> {
  const { fonts } = input;
  await Promise.all([
    document.fonts.load(`800 92px ${fonts.ui}`),
    document.fonts.load(`500 42px ${fonts.ui}`),
    document.fonts.load(`700 30px ${fonts.mono}`),
  ]);

  const canvas = document.createElement("canvas");
  canvas.width = WALLPAPER_W;
  canvas.height = WALLPAPER_H;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("wallpaper: 2D canvas unavailable");
  const W = WALLPAPER_W;
  const H = WALLPAPER_H;
  const cx = W / 2;

  // The art is wide (1600 x 500) and the screen is tall: draw it as a band at
  // 1.5x so the skyline and Sea Link stay in frame, with the sky extended above
  // (the lock-screen clock sits there) and the water fading into the page below.
  const ART_SCALE = 1.5;
  const artW = 1600 * ART_SCALE;
  const artH = 500 * ART_SCALE;
  const artTop = 230;
  const artBottom = artTop + artH;

  const [scene, qr, photo] = await Promise.all([
    svgToImage(input.scene, artW, artH),
    svgToImage(input.qr, 560, 560),
    input.avatarSrc ? loadPhoto(input.avatarSrc) : Promise.resolve(null),
  ]);
  const page = ctx.createLinearGradient(0, 0, 0, H);
  page.addColorStop(0, PAGE);
  page.addColorStop(1, "#E9E6FB");
  ctx.fillStyle = page;
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = input.edges.sky;
  ctx.fillRect(0, 0, W, artTop + 2);
  ctx.drawImage(scene, (W - artW) / 2, artTop, artW, artH);
  const fade = ctx.createLinearGradient(0, artBottom - 220, 0, artBottom);
  fade.addColorStop(0, "rgba(243,241,251,0)");
  fade.addColorStop(1, PAGE);
  ctx.fillStyle = fade;
  ctx.fillRect(0, artBottom - 220, W, 222);

  // The photo sits where the water fades out, like the card's identity card.
  const avatarR = 112;
  const avatarY = artBottom - 10;
  ctx.save();
  ctx.shadowColor = "rgba(30,27,75,0.35)";
  ctx.shadowBlur = 40;
  ctx.shadowOffsetY = 16;
  ctx.beginPath();
  ctx.arc(cx, avatarY, avatarR + 9, 0, Math.PI * 2);
  ctx.fillStyle = "#ffffff";
  ctx.fill();
  ctx.restore();
  ctx.save();
  ctx.beginPath();
  ctx.arc(cx, avatarY, avatarR, 0, Math.PI * 2);
  ctx.clip();
  if (photo) {
    const side = Math.min(photo.naturalWidth, photo.naturalHeight);
    ctx.drawImage(photo, (photo.naturalWidth - side) / 2, (photo.naturalHeight - side) / 2, side, side, cx - avatarR, avatarY - avatarR, avatarR * 2, avatarR * 2);
  } else {
    ctx.fillStyle = "#6C5CE7";
    ctx.fillRect(cx - avatarR, avatarY - avatarR, avatarR * 2, avatarR * 2);
    ctx.fillStyle = "#ffffff";
    ctx.font = `800 84px ${fonts.ui}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(input.initials, cx, avatarY + 4);
  }
  ctx.restore();

  ctx.textAlign = "center";
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = INK;
  fitFont(ctx, input.name, 800, fonts.ui, 92, 54, W - 140);
  ctx.fillText(ellipsize(ctx, input.name, W - 140), cx, avatarY + avatarR + 112);

  let y = avatarY + avatarR + 180;
  if (input.headline) {
    ctx.font = `500 42px ${fonts.ui}`;
    ctx.fillStyle = SOFT;
    ctx.fillText(ellipsize(ctx, input.headline, W - 160), cx, y);
    y += 38;
  }
  if (input.hereFor) {
    const label = `Here for · ${input.hereFor}`;
    ctx.font = `700 38px ${fonts.ui}`;
    const chipW = ctx.measureText(label).width + 72;
    roundRect(ctx, cx - chipW / 2, y + 22, chipW, 74, 37);
    ctx.fillStyle = "#6C5CE7";
    ctx.fill();
    ctx.fillStyle = "#ffffff";
    ctx.fillText(label, cx, y + 72);
    y += 96;
  }

  // QR on plain white with its quiet zone: no artwork behind the code.
  const qrSide = 560;
  const panelW = 640;
  const panelH = 690;
  const panelY = y + 50;
  ctx.save();
  ctx.shadowColor = "rgba(30,27,75,0.22)";
  ctx.shadowBlur = 60;
  ctx.shadowOffsetY = 24;
  roundRect(ctx, cx - panelW / 2, panelY, panelW, panelH, 56);
  ctx.fillStyle = "#ffffff";
  ctx.fill();
  ctx.restore();
  ctx.drawImage(qr, cx - qrSide / 2, panelY + 40, qrSide, qrSide);
  ctx.fillStyle = INK;
  fitFont(ctx, input.permalink, 700, fonts.mono, 38, 24, panelW - 80);
  ctx.fillText(input.permalink, cx, panelY + panelH - 50);

  ctx.font = `500 36px ${fonts.ui}`;
  ctx.fillStyle = SOFT;
  ctx.fillText("Scan to open my Zynd card", cx, panelY + panelH + 72);

  const badge = "MUMBAI BUILDER WEEK ’26";
  ctx.font = `700 30px ${fonts.mono}`;
  const markH = 40;
  const badgeW = ctx.measureText(badge).width + 64 + 40;
  const badgeY = panelY + panelH + 116;
  roundRect(ctx, cx - badgeW / 2, badgeY, badgeW, 68, 34);
  ctx.fillStyle = "rgba(255,255,255,0.8)";
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = "#D7D1FF";
  ctx.stroke();
  drawEthMark(ctx, cx - badgeW / 2 + 30, badgeY + 14, markH);
  ctx.fillStyle = INK;
  ctx.textAlign = "left";
  ctx.fillText(badge, cx - badgeW / 2 + 70, badgeY + 45);

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
