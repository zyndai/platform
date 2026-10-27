import Script from "next/script";

// Zynd-wide GA4 property, shared with www.zynd.ai and persona.
const ZYND_GA_ID = "G-MZ5HW7D8H9";
// Cards' own GA4 property.
const CARDS_GA_ID = "G-P4874SJZEQ";

// gtag.js is fetched with one ID and configures the rest from the dataLayer, so
// that ID has to exist: Google 404s a deleted property (the old cards default,
// G-Z0P2VTWZ35, did) and a 404 here stops every property from getting hits.
export function GoogleTags() {
  const ids = [ZYND_GA_ID, CARDS_GA_ID];
  return (
    <>
      <Script strategy="lazyOnload" src={`https://www.googletagmanager.com/gtag/js?id=${ids[0]}`} />
      <Script id="gtag-config" strategy="lazyOnload">
        {`
          window.dataLayer = window.dataLayer || [];
          function gtag(){dataLayer.push(arguments);}
          gtag('js', new Date());
          ${ids.map((id) => `gtag('config', '${id}');`).join("\n          ")}
        `}
      </Script>
    </>
  );
}
