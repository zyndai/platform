/* "QR wallpaper": a phone lock-screen image with the edition artwork, who the
 * owner is and their card's QR, so a builder can show it without opening the
 * site. Drawn in the browser from the same SVGs the QR screen shows. */

/** 1170 x 2532 is the iPhone 12-15 screen; other phones crop the sides a little. */
export const WALLPAPER_W = 1170;
export const WALLPAPER_H = 2532;

export interface WallpaperInput {
  scene: SVGSVGElement;
  /** Sky and water colours the art is extended with above and below. */
  edges: { sky: string; water: string };
  qr: SVGSVGElement;
  avatarSrc: string | null;
  initials: string;
  name: string;
  headline: string;
  hereFor: string | null;
  permalink: string;
  /** Resolved CSS font stacks for the edition's display, UI and pixel faces. */
  fonts: { display: string; ui: string; pixel: string };
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

export async function renderWallpaper(input: WallpaperInput): Promise<Blob> {
  const { fonts } = input;
  await Promise.all([
    document.fonts.load(`700 96px ${fonts.display}`),
    document.fonts.load(`600 44px ${fonts.ui}`),
    document.fonts.load(`500 40px ${fonts.pixel}`),
  ]);

  const canvas = document.createElement("canvas");
  canvas.width = WALLPAPER_W;
  canvas.height = WALLPAPER_H;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("wallpaper: 2D canvas unavailable");
  const W = WALLPAPER_W;
  const H = WALLPAPER_H;
  const cx = W / 2;

  // The art is wide (1600 x 640) and the screen is tall: draw it as a band at
  // 1.5x, which keeps the moon and the whole Gateway in frame, and extend its
  // sky and water above and below instead of cropping it into a sliver.
  const ART_SCALE = 1.5;
  const artW = 1600 * ART_SCALE;
  const artH = 640 * ART_SCALE;
  const artTop = 250;
  const waterline = artTop + 520 * ART_SCALE;

  const [scene, qr, photo] = await Promise.all([
    svgToImage(input.scene, artW, artH),
    svgToImage(input.qr, 560, 560),
    input.avatarSrc ? loadPhoto(input.avatarSrc) : Promise.resolve(null),
  ]);
  ctx.fillStyle = input.edges.sky;
  ctx.fillRect(0, 0, W, artTop + 2);
  ctx.fillStyle = input.edges.water;
  ctx.fillRect(0, artTop + artH - 2, W, H - artTop - artH + 2);
  ctx.drawImage(scene, (W - artW) / 2, artTop, artW, artH);
  // The moon's glow is cut off at the art's top edge; fade that edge into the sky.
  const seam = ctx.createLinearGradient(0, artTop, 0, artTop + 220);
  seam.addColorStop(0, input.edges.sky);
  seam.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = seam;
  ctx.fillRect(0, artTop, W, 220);
  // Stars in the extended sky, placed by a fixed sequence so every export matches.
  let seed = 7;
  const next = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  ctx.fillStyle = "#ffffff";
  for (let i = 0; i < 40; i++) {
    ctx.globalAlpha = 0.3 + next() * 0.6;
    ctx.beginPath();
    ctx.arc(next() * W, next() * artTop, 1 + next() * 2.2, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  // Darken the water so the name and QR read clearly; the sky stays bright.
  const scrim = ctx.createLinearGradient(0, waterline - 160, 0, H);
  scrim.addColorStop(0, "rgba(9,11,42,0)");
  scrim.addColorStop(0.25, "rgba(9,11,42,0.55)");
  scrim.addColorStop(1, "rgba(9,11,42,0.9)");
  ctx.fillStyle = scrim;
  ctx.fillRect(0, waterline - 160, W, H - waterline + 160);

  // The photo sits on the waterline, like the card banner; the sky above it is
  // left to the lock-screen clock.
  const avatarR = 104;
  const avatarY = waterline + 40;
  ctx.save();
  ctx.beginPath();
  ctx.arc(cx, avatarY, avatarR + 18, 0, Math.PI * 2);
  ctx.fillStyle = "rgba(95,227,214,0.18)";
  ctx.fill();
  ctx.beginPath();
  ctx.arc(cx, avatarY, avatarR, 0, Math.PI * 2);
  ctx.clip();
  if (photo) {
    const side = Math.min(photo.naturalWidth, photo.naturalHeight);
    ctx.drawImage(photo, (photo.naturalWidth - side) / 2, (photo.naturalHeight - side) / 2, side, side, cx - avatarR, avatarY - avatarR, avatarR * 2, avatarR * 2);
  } else {
    ctx.fillStyle = "#121338";
    ctx.fillRect(cx - avatarR, avatarY - avatarR, avatarR * 2, avatarR * 2);
    ctx.fillStyle = "#FFF8F0";
    ctx.font = `700 84px ${fonts.display}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(input.initials, cx, avatarY + 4);
  }
  ctx.restore();
  ctx.beginPath();
  ctx.arc(cx, avatarY, avatarR, 0, Math.PI * 2);
  ctx.lineWidth = 7;
  ctx.strokeStyle = "#5FE3D6";
  ctx.stroke();

  ctx.textAlign = "center";
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = "#FFF8F0";
  fitFont(ctx, input.name, 700, fonts.display, 96, 56, W - 140);
  ctx.fillText(ellipsize(ctx, input.name, W - 140), cx, avatarY + avatarR + 110);

  let y = avatarY + avatarR + 176;
  if (input.headline) {
    ctx.font = `500 44px ${fonts.ui}`;
    ctx.fillStyle = "rgba(255,248,240,0.84)";
    ctx.fillText(ellipsize(ctx, input.headline, W - 160), cx, y);
    y += 40;
  }
  if (input.hereFor) {
    const label = `Here for · ${input.hereFor}`;
    ctx.font = `600 40px ${fonts.ui}`;
    const chipW = ctx.measureText(label).width + 72;
    roundRect(ctx, cx - chipW / 2, y + 22, chipW, 76, 38);
    ctx.fillStyle = "#6C5CE7";
    ctx.fill();
    ctx.fillStyle = "#fff";
    ctx.fillText(label, cx, y + 74);
    y += 98;
  }

  // QR on plain white with its quiet zone: no artwork behind the code.
  const qrSide = 560;
  const panelW = 640;
  const panelH = 690;
  const panelY = y + 50;
  ctx.save();
  ctx.shadowColor = "rgba(0,0,0,0.45)";
  ctx.shadowBlur = 60;
  ctx.shadowOffsetY = 24;
  roundRect(ctx, cx - panelW / 2, panelY, panelW, panelH, 56);
  ctx.fillStyle = "#ffffff";
  ctx.fill();
  ctx.restore();
  ctx.drawImage(qr, cx - qrSide / 2, panelY + 40, qrSide, qrSide);
  ctx.fillStyle = "#121338";
  fitFont(ctx, input.permalink, 600, `ui-monospace, "SFMono-Regular", Menlo, monospace`, 40, 26, panelW - 80);
  ctx.fillText(input.permalink, cx, panelY + panelH - 52);

  ctx.font = `500 36px ${fonts.ui}`;
  ctx.fillStyle = "rgba(255,248,240,0.75)";
  ctx.fillText("Scan to open my Zynd card", cx, panelY + panelH + 70);

  const badge = "MUMBAI ’26 · LIMITED EDITION";
  ctx.font = `500 32px ${fonts.pixel}`;
  const badgeW = ctx.measureText(badge).width + 64;
  const badgeY = panelY + panelH + 110;
  roundRect(ctx, cx - badgeW / 2, badgeY, badgeW, 64, 32);
  ctx.fillStyle = "rgba(18,19,56,0.4)";
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = "rgba(255,255,255,0.55)";
  ctx.stroke();
  ctx.fillStyle = "#FFF8F0";
  ctx.fillText(badge, cx, badgeY + 43);

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
