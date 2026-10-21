import { BadgeCheck, Link2, MapPin } from "lucide-react";
import { EDITION_FONT_VARS } from "@/components/editions/fonts";
import { MumbaiScene } from "@/components/editions/mumbai-scene";
import { EDITION_NAME, HERE_FOR_LABEL, type CardEdition } from "@/lib/editions";
import { EditionQrButton } from "./edition-qr";
import "@/components/editions/edition.css";

interface Props {
  edition: CardEdition;
  name: string;
  headline: string;
  location: string;
  avatarSrc: string | null;
  initials: string;
  /** Full card URL, encoded in the QR. */
  url: string;
  /** The same URL without the scheme, as printed on the card. */
  permalink: string;
  handle: string;
  verified: boolean;
}

/** Top of a public card that uses a limited edition: the artwork, who this is,
 *  why they're here, and the QR people scan in person. */
export function EditionBanner({ edition, name, headline, location, avatarSrc, initials, url, permalink, handle, verified }: Props) {
  const hereFor = edition.here_for ? HERE_FOR_LABEL[edition.here_for] : null;
  return (
    <section className={`ed ed-banner ${EDITION_FONT_VARS}`} aria-label={`${EDITION_NAME[edition.id]} card`}>
      <div className="ed-banner-art">
        <MumbaiScene mood={edition.mood} idPrefix="ed-banner" focus="center" crop={[96, 590]} />
        <span className="ed-pixel-badge">MUMBAI ’26 · LIMITED EDITION</span>
      </div>
      <div className="ed-banner-body">
        {avatarSrc ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img className="ed-avatar" src={avatarSrc} alt={name} />
        ) : (
          <span className="ed-avatar" role="img" aria-label={name}
            style={{ display: "flex", alignItems: "center", justifyContent: "center", color: "#FFF8F0", font: "700 40px/1 var(--ed-display), Georgia, serif" }}>
            {initials}
          </span>
        )}
        <div className="ed-who">
          <div className="ed-name">
            <span>{name}</span>
            {verified && <BadgeCheck size={24} color="#6C5CE7" aria-label="LinkedIn linked" />}
          </div>
          {headline && <div className="ed-headline">{headline}</div>}
          <div className="ed-meta">
            {location && <span><MapPin size={15} aria-hidden />{location}</span>}
            <span><Link2 size={15} aria-hidden />{permalink}</span>
          </div>
        </div>
        <div className="ed-actions">
          {hereFor && <span className="ed-chip">Here for · {hereFor}</span>}
          <EditionQrButton
            edition={edition}
            url={url}
            permalink={permalink}
            handle={handle}
            name={name}
            headline={headline}
            avatarSrc={avatarSrc}
            initials={initials}
          />
        </div>
      </div>
    </section>
  );
}
