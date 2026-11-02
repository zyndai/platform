"use client";

import { useEffect, useRef, useState } from "react";
import { RecapArt } from "./recap-art";
import type { Recap } from "@/lib/recaps";

export function RecapPreview({ recap }: { recap: Recap }) {
  const frame = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0);
  useEffect(() => {
    if (!frame.current) return;
    const observer = new ResizeObserver(([entry]) => setScale(entry.contentRect.width / 1200));
    observer.observe(frame.current);
    return () => observer.disconnect();
  }, []);
  return <div ref={frame} className="recap-art-frame" role="img" aria-label={`${recap.snapshot.name}'s ${recap.snapshot.label} recap`}>
    <div className="recap-art-inner" style={{ transform: `scale(${scale})` }} aria-hidden="true"><RecapArt recap={recap} /></div>
  </div>;
}
