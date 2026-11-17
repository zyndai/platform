import { parseHelpOffer } from "@/lib/help-offer";

const chipStyle = {
  background: "rgba(255,255,255,0.16)",
  borderRadius: 999,
  padding: "3px 8px",
  fontSize: "0.62rem",
  fontWeight: 600,
} as const;

/**
 * One "Can help with" chip on a public card. A plain topic renders exactly as before.
 * A priced topic (see lib/help-offer.ts) shows its price, and links to the owner's
 * booking page when there is one. Nothing is charged here.
 */
export function HelpChip({ label, requestUrl }: { label: string; requestUrl?: string | null }) {
  const offer = parseHelpOffer(label);
  if (!offer) return <span style={chipStyle}>{label}</span>;
  return (
    <span style={chipStyle}>
      {offer.topic} <strong style={{ fontWeight: 800 }}>{offer.price}</strong>
      {requestUrl && (
        <>
          {" · "}
          <a
            href={requestUrl}
            target="_blank"
            rel="noreferrer"
            style={{ color: "inherit", fontWeight: 800, textDecoration: "underline" }}
          >
            Request this
          </a>
        </>
      )}
    </span>
  );
}
