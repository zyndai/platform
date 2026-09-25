"use client";

import { useEffect, useState } from "react";
import QRCodeLib from "qrcode";

interface QrCodeProps {
  value: string;
  size?: number;
  // Hex colors. Dark = the modules, light = the background. Default mirrors
  // the share-card palette so the QR sits cleanly on a cream surface.
  dark?: string;
  light?: string;
  className?: string;
  ariaLabel?: string;
}

/**
 * Renders a scannable QR for `value` as an inline SVG. Falls back to
 * an empty span while generating (first render after `value` changes)
 * so callers can layout-reserve the box.
 */
export function QrCode({
  value,
  size = 200,
  dark = "#17120d",
  light = "#fffaf0",
  className,
  ariaLabel,
}: QrCodeProps) {
  const [svg, setSvg] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    if (!value) {
      setSvg("");
      return;
    }
    QRCodeLib.toString(value, {
      type: "svg",
      errorCorrectionLevel: "M",
      margin: 1,
      width: size,
      color: { dark, light },
    })
      .then((out) => {
        if (!cancelled) setSvg(out);
      })
      .catch(() => {
        if (!cancelled) setSvg("");
      });
    return () => {
      cancelled = true;
    };
  }, [value, size, dark, light]);

  return (
    <span
      className={className}
      role="img"
      aria-label={ariaLabel || `QR code linking to ${value}`}
      style={{ display: "inline-block", width: size, height: size }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
