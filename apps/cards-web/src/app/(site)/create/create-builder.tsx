"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { useAuth } from "@/hooks/useAuth";
import { useMyCard } from "@/hooks/useMyCard";
import { CARDS_API } from "@/lib/cards";
import { setClaimHandle } from "@/lib/auth/next-cookie";
import { startLinkedInOAuth } from "@/lib/auth/session";
import { AboutCard } from "./about-card";
import { CHIP_GROUPS, addCustomValues, emptySelections, hasLabel, sameLabel, type ChipGroupId, type Selections } from "./chips";
import { DetailsCard } from "./details-card";
import { saveDraft, takeDraft, type Draft } from "./draft";
import { LiveCard } from "./live-card";
import {
  applyEdits, buildUserAnswers, cleanHandle, detectKind, finalizeCard, liveIdentity, normalizeUrl, statusLine,
  type DraftEdits, type TopicAnswers,
} from "./model";
import { PublishCard } from "./publish-card";
import { claimPublished, getToken, publishCard, rememberPublished, syncMemoryOnClaim } from "./publish";
import { AlreadyHaveCard, CardExists, PublishedScreen } from "./screens";
import { SourcesCard } from "./sources-card";
import { useBuild } from "./use-build";
import type { AgentProfileCard } from "@/lib/cards";
import "./create.css";

interface ClaimCandidate { handle: string; name: string; headline: string }

/**
 * Create a card on one page. Paste a link and the build starts on its own;
 * each source shows what was read, the AI suggests the answers, and the card
 * previews live beside the form. Nothing is public until Publish.
 */
export function CreateBuilder() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const notice = searchParams.get("notice");
  const seededUrl = searchParams.get("url");
  const { authenticated, user } = useAuth();
  const { handle: ownHandle, card: ownCard } = useMyCard();

  const [urls, setUrls] = useState<string[]>([]);
  const [resume, setResume] = useState<File | null>(null);

  // What the person chose. A group they never touched follows the AI's suggestion.
  const [picks, setPicks] = useState<Draft["picks"]>({});
  const [locationEdit, setLocationEdit] = useState<string | null>(null);
  const [calendly, setCalendly] = useState("");
  const [googleCalendar, setGoogleCalendar] = useState("");
  const [edits, setEdits] = useState<DraftEdits>({});
  const [excluded, setExcluded] = useState<ReadonlySet<string>>(new Set());
  const [customHandle, setCustomHandle] = useState(() => cleanHandle(searchParams.get("handle") ?? ""));

  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState<string | null>(null);
  const [published, setPublished] = useState<{ handle: string; card: AgentProfileCard } | null>(null);
  const [existsHandle, setExistsHandle] = useState<string | null>(null);
  const [claimCandidates, setClaimCandidates] = useState<ClaimCandidate[]>([]);
  const [claimDismissed, setClaimDismissed] = useState(false);

  const alreadyHasCard = authenticated && !!ownHandle;
  const building = !published && !existsHandle && !alreadyHasCard;
  const { build, retry } = useBuild({ urls, resume, enabled: building });

  // Links from the landing page's paste bar, and a draft saved before a sign-in round trip.
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current) return;
    seeded.current = true;
    const saved = takeDraft();
    const fromLink = (seededUrl ?? "").split(/\s+/).map(normalizeUrl).flatMap((r) => (r && "url" in r ? [r.url] : []));
    const all = [...new Set([...(saved?.urls ?? []), ...fromLink])];
    // sessionStorage has no value while rendering on the server, so the saved draft
    // can only be applied after mount; reading it during render would mismatch hydration.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (all.length) setUrls(all);
    if (!saved) return;
    setPicks(saved.picks);
    setLocationEdit(saved.location);
    setCalendly(saved.calendly);
    setGoogleCalendar(saved.googleCalendar);
    if (saved.handle) setCustomHandle(saved.handle);
  }, [seededUrl]);

  // Claim before build: a published, unclaimed card may already match this LinkedIn.
  const linkedinUrl = urls.find((u) => detectKind(u) === "linkedin") ?? "";
  useEffect(() => {
    if (!linkedinUrl || !building) return;
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const res = await fetch(`${CARDS_API}/onboard/claim-candidates?linkedin=${encodeURIComponent(linkedinUrl)}`);
        if (!res.ok || cancelled) return;
        const data = await res.json();
        if (!cancelled) setClaimCandidates(Array.isArray(data.candidates) ? data.candidates : []);
      } catch { /* non-fatal */ }
    }, 500);
    return () => { cancelled = true; clearTimeout(t); };
  }, [linkedinUrl, building]);

  // Signing in on the "you're live" screen claims the card.
  useEffect(() => {
    if (!authenticated || !published) return;
    void getToken().then((token) => { if (token) void claimPublished(token, published.handle, published.card); });
  }, [authenticated, published]);

  // ── the card as it will be published ──
  const suggested: Selections = build.card ? {
    working_on: build.card.working_on,
    can_help: build.card.can_help_with,
    connect_with: build.card.connect_with,
    love_talking: build.card.love_talking_about,
  } : emptySelections();
  const selections: Selections = {
    working_on: picks.working_on ?? suggested.working_on,
    can_help: picks.can_help ?? suggested.can_help,
    connect_with: picks.connect_with ?? suggested.connect_with,
    love_talking: picks.love_talking ?? suggested.love_talking,
  };
  const topics: TopicAnswers = {
    working_on: selections.working_on,
    can_help_with: selections.can_help,
    connect_with: selections.connect_with,
    love_talking_about: selections.love_talking,
  };
  const draft = build.card ? applyEdits(build.card, edits) : null;
  const guessedLocation = build.card?.identity.location ?? "";
  const location = locationEdit ?? guessedLocation;
  const finalCard = draft ? finalizeCard(draft, topics, location, excluded) : null;
  const canPublish = build.status === "ready" && !!finalCard && !!build.jobId;
  const hasSource = urls.length > 0 || resume !== null;

  // ── handlers ──
  const addUrl = (raw: string): string | null => {
    const result = normalizeUrl(raw);
    if (!result) return null;
    if ("error" in result) return result.error;
    setUrls((prev) => (prev.includes(result.url) ? prev : [...prev, result.url]));
    return null;
  };
  const replaceUrl = (old: string, raw: string): string | null => {
    const result = normalizeUrl(raw);
    if (!result) return "Enter a link.";
    if ("error" in result) return result.error;
    setUrls((prev) => [...new Set(prev.map((u) => (u === old ? result.url : u)))]);
    return null;
  };
  const toggleChip = (id: ChipGroupId, label: string) => setPicks((prev) => {
    const current = prev[id] ?? suggested[id];
    return { ...prev, [id]: hasLabel(current, label) ? current.filter((x) => !sameLabel(x, label)) : [...current, label] };
  });
  const addChip = (id: ChipGroupId, raw: string) => setPicks((prev) => {
    const group = CHIP_GROUPS.find((g) => g.id === id)!;
    return { ...prev, [id]: addCustomValues(prev[id] ?? suggested[id], group.options, raw) };
  });
  const toggleExcluded = (key: string) => setExcluded((prev) => {
    const next = new Set(prev);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });

  const signIn = () => {
    saveDraft({ urls, picks, location: locationEdit, calendly, googleCalendar, handle: customHandle });
    void startLinkedInOAuth("/create", "card");
  };
  const claim = () => {
    if (!published) return;
    setClaimHandle(published.handle);
    void startLinkedInOAuth(`/p/${encodeURIComponent(published.handle)}`, "card");
  };

  async function publish() {
    if (!finalCard || !build.jobId || build.status !== "ready") return;
    setPublishing(true);
    setPublishError(null);
    let leaving = false;
    try {
      const token = await getToken();
      const result = await publishCard({
        jobId: build.jobId,
        card: finalCard,
        userAnswers: buildUserAnswers(topics, location, calendly, googleCalendar),
        customHandle,
        ownerEmail: user?.email ?? null,
        token,
      });
      if (result.kind === "existing") {
        setExistsHandle(result.handle);
        return;
      }
      rememberPublished(result.handle, result.claimToken);
      setClaimHandle(result.handle);
      takeDraft();
      // A signed-in creator goes straight to the "ask your own card" welcome:
      // no login wall after publishing.
      if (authenticated) {
        if (token) void syncMemoryOnClaim(token, result.handle, finalCard);
        leaving = true;
        router.push(`/p/${encodeURIComponent(result.handle)}/welcome`);
        return;
      }
      // Anonymous: stay and show the "you're live" screen; signing in is offered there.
      setPublished({ handle: result.handle, card: finalCard });
    } catch (err) {
      setPublishError(err instanceof Error ? err.message : "Failed to publish");
    } finally {
      if (!leaving) setPublishing(false);
    }
  }

  // ── what to show ──
  if (existsHandle) return <CardExists handle={existsHandle} authenticated={authenticated} />;
  if (published) return <PublishedScreen handle={published.handle} authenticated={authenticated} onClaim={claim} />;
  if (alreadyHasCard) return <AlreadyHaveCard handle={ownHandle!} published={ownCard?.status === "published"} />;

  const statusText = build.status === "error" ? "Fix the problem above, then try again." : statusLine(build.sources, build.stage);
  const candidates = linkedinUrl && !claimDismissed ? claimCandidates.slice(0, 3) : [];

  return (
    <>
      <section className="dc-hero">
        <div className="dc-hero-copy">
          <span className="dc-eyebrow"><span className="dc-eyebrow-dot" /> You approve before anything goes live</span>
          {/* div, not h1: globals.css makes every h1 uppercase gradient text */}
          <div role="heading" aria-level={1} className="dc-title">Create your card</div>
          <p className="dc-lede">
            Paste a link. Your card writes itself while you watch.
          </p>
        </div>
      </section>

      {notice === "no-profile" && (
        <div className="cr-banner" style={{ marginTop: 16 }}>
          <div className="cr-h" style={{ fontSize: 15 }}>No profile card on this account</div>
          <div className="cr-sub">We signed you in, but there&apos;s no card linked to this email yet. Create one below. It takes about a minute.</div>
        </div>
      )}
      {notice === "lookup-failed" && (
        <div className="cr-banner" style={{ marginTop: 16, borderLeftColor: "#B91C1C" }}>
          <div className="cr-h" style={{ fontSize: 15 }}>Couldn&apos;t check for an existing profile</div>
          <div className="cr-sub">Sign-in worked, but we couldn&apos;t reach the cards service. You can create a card below or try signing in again in a moment.</div>
        </div>
      )}
      {candidates.length > 0 && (
        <div className="cr-banner" style={{ marginTop: 16 }}>
          <div className="cr-h" style={{ fontSize: 15 }}>We found a card that looks like yours</div>
          <div className="cr-sub">It was assembled from public data and hasn&apos;t been claimed yet. Claiming it beats building a duplicate.</div>
          {candidates.map((c) => (
            <div key={c.handle} className="cr-banner-row">
              <div>
                <div className="cr-clip" style={{ fontWeight: 800 }}>{c.name}</div>
                {c.headline && <div className="cr-clip cr-note">{c.headline}</div>}
              </div>
              <Link href={`/p/${encodeURIComponent(c.handle)}`} className="dc-btn dc-btn-primary" style={{ height: 36, padding: "0 14px", fontSize: 13 }}>Is this you?</Link>
            </div>
          ))}
          <div><button type="button" className="dc-linkbtn" onClick={() => setClaimDismissed(true)}>No, build a new one</button></div>
        </div>
      )}

      <div className="cr-layout">
        <div className="cr-main">
          <SourcesCard
            urls={urls} resume={resume} build={build}
            onAdd={addUrl} onReplace={replaceUrl} onRetry={retry} onResume={setResume}
            onRemove={(url) => setUrls((prev) => prev.filter((u) => u !== url))}
          />
          <AboutCard
            selections={selections} suggested={suggested} building={build.status === "running"}
            location={location} locationHint={guessedLocation}
            calendly={calendly} googleCalendar={googleCalendar}
            onToggle={toggleChip} onAdd={addChip}
            onLocation={setLocationEdit} onCalendly={setCalendly} onGoogleCalendar={setGoogleCalendar}
          />
          <DetailsCard
            card={draft} building={build.status === "running"} hasSource={hasSource}
            onEdit={(patch) => setEdits((prev) => ({ ...prev, ...patch }))}
            excluded={excluded} onToggleExcluded={toggleExcluded}
          />
        </div>

        <aside className="cr-aside">
          <LiveCard live={liveIdentity(build.sources)} card={finalCard} building={build.status === "running"} handle={customHandle} />
          <PublishCard
            ready={canPublish} building={build.status === "running"} hasSource={hasSource} statusText={statusText}
            handle={customHandle} onHandle={setCustomHandle}
            authenticated={authenticated} onSignIn={signIn}
            onPublish={() => void publish()} publishing={publishing} error={publishError}
          />
        </aside>
      </div>
    </>
  );
}
