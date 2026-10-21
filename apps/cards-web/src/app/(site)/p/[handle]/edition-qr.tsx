"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Loader2, Moon, QrCode, Sun, X } from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { EDITION_FONT_VARS } from "@/components/editions/fonts";
import { EthMark } from "@/components/editions/eth-mark";
import { MumbaiSkyline } from "@/components/editions/mumbai-skyline";
import { withShareRef } from "@/lib/attr";
import { HERE_FOR_LABEL, type CardEdition } from "@/lib/editions";
import { track } from "@/lib/track";
import { renderWallpaper, saveWallpaper, type WallpaperTheme } from "./edition-wallpaper";

interface Props {
  edition: CardEdition;
  /** Span the whole row of the action grid (no social links beside it). */
  wide?: boolean;
  url: string;
  permalink: string;
  handle: string;
  name: string;
  headline: string;
  avatarSrc: string | null;
  initials: string;
}

/** Keeps the phone screen on while the QR is up, so it doesn't dim in the
 *  middle of someone scanning it. Not every browser supports it; the QR works
 *  the same without it. */
function useScreenAwake(active: boolean) {
  useEffect(() => {
    if (!active || !("wakeLock" in navigator)) return;
    let sentinel: WakeLockSentinel | null = null;
    let released = false;
    const acquire = () => {
      navigator.wakeLock.request("screen")
        .then((lock) => {
          if (released) void lock.release();
          else sentinel = lock;
        })
        .catch((err: unknown) => {
          // Denied (battery saver, unfocused tab): the screen may dim, nothing else changes.
          console.warn("edition QR: screen wake lock unavailable", err);
        });
    };
    // The browser drops the lock whenever the tab is hidden (app switch, lock
    // button); take it again when the QR is back on screen.
    const onVisible = () => {
      if (document.visibilityState === "visible" && !released) acquire();
    };
    acquire();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      released = true;
      document.removeEventListener("visibilitychange", onVisible);
      if (sentinel) void sentinel.release();
    };
  }, [active]);
}

/** Stops the page behind the dialog from scrolling; returns the undo. */
function lockPageScroll(): () => void {
  const previous = document.body.style.overflow;
  document.body.style.overflow = "hidden";
  return () => {
    document.body.style.overflow = previous;
  };
}

export function EditionQrButton({ edition, wide = false, url, permalink, handle, name, headline, avatarSrc, initials }: Props) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  // Which wallpaper is being made, or whether the last attempt failed.
  const [wallpaper, setWallpaper] = useState<WallpaperTheme | "idle" | "error">("idle");
  useScreenAwake(open);

  async function saveAsWallpaper(theme: WallpaperTheme) {
    const overlay = overlayRef.current;
    const art = overlay?.querySelector<SVGSVGElement>(`svg.ed-wall-${theme}`);
    const qr = overlay?.querySelector<SVGSVGElement>(".ed-qr-panel svg");
    if (!overlay || !art || !qr || wallpaper === "light" || wallpaper === "dark") return;
    setWallpaper(theme);
    try {
      const css = getComputedStyle(overlay);
      const png = await renderWallpaper({
        theme, art, qr, avatarSrc, initials, name, headline, hereFor, permalink,
        fonts: {
          ui: css.getPropertyValue("--ed-ui").trim() || "system-ui, sans-serif",
          mono: css.getPropertyValue("--ed-mono").trim() || "ui-monospace, monospace",
        },
      });
      const outcome = await saveWallpaper(png, `zynd-${handle}-mumbai-26-wallpaper-${theme}.png`);
      if (outcome !== "cancelled") track("share_click", { handle, target: `edition_wallpaper_${theme}` }, handle);
      setWallpaper("idle");
    } catch (err) {
      console.error("edition QR: wallpaper export failed", err);
      setWallpaper("error");
    }
  }

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const trigger = triggerRef.current;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
        return;
      }
      // Keep Tab inside the dialog: the page behind it is inert while it's open.
      if (e.key !== "Tab") return;
      const focusables = overlayRef.current?.querySelectorAll<HTMLElement>("button:not([disabled])");
      if (!focusables?.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    const unlockPageScroll = lockPageScroll();
    return () => {
      document.removeEventListener("keydown", onKey);
      unlockPageScroll();
      trigger?.focus();
    };
  }, [open]);

  const hereFor = edition.here_for ? HERE_FOR_LABEL[edition.here_for] : null;
  const qrValue = withShareRef(url, handle);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={`ed-qr-btn${wide ? " is-wide" : ""}`}
        onClick={() => {
          track("share_click", { handle, target: "edition_qr" }, handle);
          setOpen(true);
        }}
      >
        <QrCode size={17} aria-hidden /> Show my QR
      </button>
      {open && createPortal(
        <div ref={overlayRef} className={`ed ed-qr-overlay ${EDITION_FONT_VARS}`} role="dialog" aria-modal="true" aria-labelledby={titleId}>
          <div className="ed-qr-art" aria-hidden>
            <MumbaiSkyline idPrefix="ed-qr" className="ed-qr-bg" focus="bottom" />
          </div>
          <button ref={closeRef} type="button" className="ed-qr-close" onClick={() => setOpen(false)} aria-label="Close QR code">
            <X size={20} />
          </button>
          <div className="ed-qr-sheet">
            {avatarSrc ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img className="ed-qr-avatar" src={avatarSrc} alt="" />
            ) : (
              <span className="ed-qr-avatar" aria-hidden
                style={{ display: "flex", alignItems: "center", justifyContent: "center", font: "800 34px/1 var(--ed-ui), system-ui, sans-serif" }}>
                {initials}
              </span>
            )}
            <div id={titleId} className="ed-qr-name">{name}</div>
            {headline && <div className="ed-qr-headline">{headline}</div>}
            {hereFor && <span className="ed-chip">Here for · {hereFor}</span>}
            <div className="ed-qr-panel">
              <QRCodeSVG value={qrValue} size={300} level="M" marginSize={4} fgColor="#1E1B4B" bgColor="#ffffff"
                title={`QR code for ${permalink}`} />
              <span className="ed-qr-url">{permalink}</span>
            </div>
            <div className="ed-qr-hint">Scan to open my Zynd card</div>
            <div className="ed-wall-label">Save as phone wallpaper</div>
            <div className="ed-wall-actions">
              {(["light", "dark"] as const).map((theme) => (
                <button key={theme} type="button" className={`ed-wallpaper-btn is-${theme}`}
                  onClick={() => void saveAsWallpaper(theme)} disabled={wallpaper === "light" || wallpaper === "dark"}>
                  {wallpaper === theme
                    ? <Loader2 size={17} className="ed-spin" aria-hidden />
                    : theme === "light" ? <Sun size={17} aria-hidden /> : <Moon size={17} aria-hidden />}
                  {theme === "light" ? "Light" : "Dark"} wallpaper
                </button>
              ))}
            </div>
            {wallpaper === "error" && <div className="ed-qr-hint" role="alert">Couldn’t make the wallpaper. Take a screenshot of this screen instead.</div>}
            {/* The skyline for each wallpaper, drawn without a sky; only ever rasterized. */}
            <div hidden>
              <MumbaiSkyline idPrefix="ed-wall-light" className="ed-wall-light" theme="light" silhouette crop={[150, 500]} />
              <MumbaiSkyline idPrefix="ed-wall-dark" className="ed-wall-dark" theme="dark" silhouette crop={[150, 500]} />
            </div>
            <span className="ed-edition-badge"><EthMark size={14} /> MUMBAI BUILDER WEEK ’26</span>
          </div>
        </div>,
        document.body,
      )}
    </>
  );
}
