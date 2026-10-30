"use client";

import { useState } from "react";
import { recapOrigin, recapPath, type Recap } from "@/lib/recaps";
import { track } from "@/lib/track";

export function RecapShare({ recap }: { recap: Recap }) {
  const [notice, setNotice] = useState("");
  const url = `${recapOrigin}${recapPath(recap)}?ref=recap`;
  async function copy(value: string, message: string) {
    try { await navigator.clipboard.writeText(value); setNotice(message); }
    catch { setNotice("Copy is unavailable in this browser. Select the text or link to copy it."); }
  }
  return <div>
    <div className="recap-controls">
      <a className="recap-button" onClick={() => track("share_click", { target: "recap_x", period: recap.period }, recap.handle)} href={`https://twitter.com/intent/tweet?url=${encodeURIComponent(url)}&text=${encodeURIComponent(recap.caption.slice(0, 180))}`} target="_blank" rel="noopener noreferrer">Share to X ↗</a>
      <a className="recap-button" onClick={() => track("share_click", { target: "recap_linkedin", period: recap.period }, recap.handle)} href={`https://www.linkedin.com/sharing/share-offsite/?url=${encodeURIComponent(url)}`} target="_blank" rel="noopener noreferrer">Share to LinkedIn ↗</a>
      <button className="recap-secondary" onClick={() => copy(`${recap.caption}\n\n${url}`, "Caption and link copied.")}>Copy caption</button>
      <button className="recap-secondary" onClick={() => copy(url, "Recap link copied.")}>Copy link</button>
    </div>
    <p className="recap-muted">Share opens your composer with the recap link. To post the image itself, download the PNG and attach it to your post.</p>
    <p role="status" aria-live="polite">{notice}</p>
  </div>;
}
