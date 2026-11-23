/**
 * A "Can help with" topic that carries a price, typed by the owner as
 * "Code review · $50" (also "|" or "•" as the separator).
 *
 * This is the v0 convention for micro-consulting (issue #124). The price stays
 * in the existing topic text, so no card field, API change or database column
 * is needed, and nothing is charged: the chip only links to the owner's booking
 * page. When offers get their own structured fields, delete this file and its
 * callers.
 */

const OFFER = /^(.+?)\s*[·•|]\s*([$£€₹])\s?(\d{1,6}(?:,\d{3})*(?:\.\d{1,2})?)$/u;

export interface HelpOffer {
  /** The topic as the owner wrote it, without the price. */
  topic: string;
  /** The price as shown on the card, e.g. "$50" or "£1,200.50". */
  price: string;
}

/** The price in a topic label, or null for a plain topic (and for a price of zero). */
export function parseHelpOffer(label: string): HelpOffer | null {
  const match = OFFER.exec(label.trim());
  if (!match) return null;
  const [, topic, symbol, amount] = match;
  if (!(Number(amount.replace(/,/g, "")) > 0)) return null;
  return { topic: topic.trim(), price: `${symbol}${amount}` };
}

/** The topic with its price removed, for anything that should not carry a price (such as declared expertise). */
export function helpTopic(label: string): string {
  return parseHelpOffer(label)?.topic ?? label;
}
