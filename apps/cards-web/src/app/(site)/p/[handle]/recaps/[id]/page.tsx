import Link from "next/link";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { fetchPublicRecap, recapOrigin, recapPath } from "@/lib/recaps";
import { RecapPreview } from "@/components/recaps/recap-preview";
import { RecapShare } from "@/components/recaps/recap-share";
import "@/components/recaps/recaps.css";

type Props = { params: Promise<{ handle: string; id: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { handle, id } = await params;
  const recap = await fetchPublicRecap(handle, id);
  if (!recap) return { title: "Recap not found", robots: { index: false, follow: false } };
  const title = `${recap.snapshot.name}'s ${recap.snapshot.label} on Zynd`;
  const image = `${recapOrigin}/api/recaps/${id}/image?handle=${encodeURIComponent(handle)}`;
  return { title, description: recap.caption, alternates: { canonical: `${recapOrigin}${recapPath(recap)}` },
    openGraph: { title, description: recap.caption, url: `${recapOrigin}${recapPath(recap)}`, images: [{ url: image, width: 1200, height: 630 }] },
    twitter: { card: "summary_large_image", title, description: recap.caption, images: [image] } };
}

export default async function PublicRecap({ params }: Props) {
  const { handle, id } = await params;
  const recap = await fetchPublicRecap(handle, id);
  if (!recap) notFound();
  return <main className="recap-page"><div className="recap-shell recap-public">
    <div className="recap-top"><Link href={`/p/${encodeURIComponent(handle)}`}>← {recap.snapshot.name}&apos;s profile</Link><span className="recap-eyebrow">Made with Zynd</span></div>
    <p className="recap-eyebrow">{recap.snapshot.label}{recap.snapshot.in_progress ? " · So far" : ""}</p>
    <h1>{recap.snapshot.name}&apos;s chapter.</h1>
    <RecapPreview recap={recap} />
    <p className="recap-caption">{recap.caption}</p>
    <ul className="recap-source-list">{recap.snapshot.highlights.map((h) => <li key={h.id}>
      <strong>{h.kind === "github" ? `${h.count} GitHub contributions` : `${h.kind === "shipped" ? "Shipped" : h.kind === "learned" ? "Learned" : "Explored"} ${h.title}`}</strong>
      <div className="recap-muted">{h.date ? `${h.date} · ` : ""}{h.source === "owner_confirmed" ? "Self-reported milestone" : h.source === "github" ? "From GitHub" : "From their public card"}
        {h.url && <> · <a href={h.url} target="_blank" rel="noopener noreferrer">View source ↗</a></>}</div>
    </li>)}</ul>
    <RecapShare recap={recap} />
    <a className="recap-button recap-secondary" href={`/api/recaps/${id}/image?handle=${encodeURIComponent(handle)}&download=1`}>Download PNG</a>
    <div className="recap-callout"><h2>Your work deserves a chapter, too.</h2><p>Zynd turns your projects and progress into a living profile.</p>
      <Link className="recap-button" href={`/create?ref=recap&from=${encodeURIComponent(handle)}`}>Create your Zynd card ↗</Link></div>
  </div></main>;
}
