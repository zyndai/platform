import Script from "next/script";

// Zynd-wide GA4 property, shared with www.zynd.ai and persona. Cards keeps its
// own property too (NEXT_PUBLIC_ANALYTICS_ID) so existing reports don't change.
const ZYND_GA_ID = "G-MZ5HW7D8H9";

export function GoogleTags() {
  const ids = Array.from(new Set([process.env.NEXT_PUBLIC_ANALYTICS_ID || "G-Z0P2VTWZ35", ZYND_GA_ID]));
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
