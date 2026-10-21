import { BadgeCheck, Clock3, FileText, Github, Linkedin, MapPin, Target, UserRound } from "lucide-react";
import { EthMark } from "@/components/editions/eth-mark";
import { EDITION_FONT_VARS } from "@/components/editions/fonts";
import { EditionBannerImage } from "@/components/editions/banner-image";
import { EDITION_NAME, HERE_FOR_LABEL, type CardEdition } from "@/lib/editions";
import { EditionAboutText } from "./edition-about";
import { EditionIdentityActions } from "./edition-actions";
import { EditionQrButton } from "./edition-qr";
import "@/components/editions/edition.css";

interface Props {
  edition: CardEdition;
  name: string;
  /** The name split for wrapping, as the classic hero does. */
  nameLines: string[];
  headline: string;
  location: string;
  /** Current role from LinkedIn, e.g. "Contributor · Zynd". */
  role: string;
  chips: string[];
  avatarSrc: string | null;
  initials: string;
  /** Full card URL, encoded in the QR. */
  url: string;
  /** The same URL without the scheme, as printed on the card. */
  permalink: string;
  handle: string;
  verified: boolean;
  /** Claimed cards have the profile chat. */
  canChat: boolean;
  /** The Connect / Message button, for visitors only. Sits at the top of the actions. */
  connect?: React.ReactNode;
  /** The card's About text; shown inside the identity card so the signal cards below size to their own content. */
  about: string;
  links: { x: string | null; github: string | null; linkedin: string | null };
  updatedLabel: string | null;
}

function XGlyph() {
  return (
    <svg viewBox="0 0 24 24" width={16} height={16} fill="currentColor" aria-hidden>
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
    </svg>
  );
}

/** Top of a card on the Mumbai Builder Week edition: the artwork, then an
 *  identity card that takes the place of the classic purple hero.
 *
 *  The identity card is two bands that share one column grid, so every edge
 *  lines up: photo + who | actions on top, About | Focus below a divider. */
export function EditionHero(props: Props) {
  const { edition, name, nameLines, headline, location, role, chips, avatarSrc, initials, url, permalink, handle, verified, canChat, connect, about, links, updatedLabel } = props;
  const hereFor = edition.here_for ? HERE_FOR_LABEL[edition.here_for] : null;
  const socials = [
    { href: links.x, label: "X", icon: <XGlyph /> },
    { href: links.github, label: "GitHub", icon: <Github size={17} aria-hidden /> },
    { href: links.linkedin, label: "LinkedIn", icon: <Linkedin size={17} aria-hidden /> },
  ].filter((s): s is { href: string; label: string; icon: React.JSX.Element } => !!s.href);
  const updated = updatedLabel ? `Updated ${updatedLabel.charAt(0)}${updatedLabel.slice(1).toLowerCase()}` : "";
  const hasFocus = chips.length > 0 || !!hereFor;

  return (
    <section className={`ed ed-hero ${EDITION_FONT_VARS}`} data-banner={edition.banner} aria-label={`${EDITION_NAME[edition.id]} card`}>
      <div className="ed-hero-art">
        <EditionBannerImage banner={edition.banner} className="ed-hero-img" priority sizes="(max-width: 820px) 600px, min(100vw, 1252px)" />
        {/* Over the clear sky at the top centre: the artwork's crystals sit at the sides. */}
        <div className="ed-hero-title">
          <span className="ed-hero-name">
            <span className="ed-hero-mark"><EthMark size={20} /></span>
            MUMBAI BUILDER WEEK<span className="ed-hero-year"> 2026</span><span className="ed-hero-short"> ’26</span>
          </span>
          <span className="ed-hero-line">BUILDERS, IN PERSON, IN MUMBAI</span>
        </div>
      </div>

      <div className="ed-id">
        <div className="ed-id-profile">
          {avatarSrc ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img className="ed-id-photo" src={avatarSrc} alt={name} />
          ) : (
            <span className="ed-id-photo ed-id-initials" role="img" aria-label={name}>{initials}</span>
          )}
          <div className="ed-id-who">
            <div className="ed-id-im">I&apos;m</div>
            <div className="ed-id-name">
              <span>{nameLines.map((line, i) => <span key={i}>{line}{i < nameLines.length - 1 ? " " : ""}</span>)}</span>
              {verified && <BadgeCheck size={26} className="ed-id-verified" aria-label="LinkedIn linked" />}
            </div>
            {headline && <div className="ed-id-headline">{headline}</div>}
            {(location || role || updated) && (
              <div className="ed-id-meta">
                {location && <span><MapPin size={15} aria-hidden />{location}</span>}
                {role && <span><UserRound size={15} aria-hidden />{role}</span>}
                {updated && <span><Clock3 size={15} aria-hidden />{updated}</span>}
              </div>
            )}
          </div>
        </div>

        {/* Two equal columns: Connect spans both; Ask Agent | handle;
            socials | Show my QR. A missing partner makes the other span. */}
        <div className="ed-id-actions">
          {connect && <div className="ed-act-connect">{connect}</div>}
          <EditionIdentityActions handle={handle} permalink={permalink} canChat={canChat} />
          {socials.length > 0 && (
            <div className="ed-act-socials" style={{ "--n": socials.length } as React.CSSProperties}>
              {socials.map((s) => (
                <a key={s.label} className="ed-social" href={s.href} target="_blank" rel="noreferrer" aria-label={s.label}>
                  {s.icon}
                  {socials.length === 1 && <span>{s.label}</span>}
                </a>
              ))}
            </div>
          )}
          <EditionQrButton edition={edition} url={url} permalink={permalink} handle={handle} name={name}
            headline={headline} avatarSrc={avatarSrc} initials={initials} wide={socials.length === 0} />
        </div>

        {(about || hasFocus) && (
          <div className={`ed-id-more${about && hasFocus ? "" : " is-single"}`}>
            {about && (
              <div className="ed-id-about">
                <div className="ed-id-label"><FileText size={15} aria-hidden /> About</div>
                <EditionAboutText text={about} />
              </div>
            )}
            {hasFocus && (
              <div className="ed-id-focus">
                <div className="ed-id-label"><Target size={15} aria-hidden /> Focus</div>
                <div className="ed-id-chips">
                  {hereFor && <span className="ed-chip">Here for · {hereFor}</span>}
                  {chips.map((chip) => <span key={chip} className="ed-tag">{chip}</span>)}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
