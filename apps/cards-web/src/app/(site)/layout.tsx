import type { Metadata } from "next";
import Script from "next/script";
import { Providers } from "@/components/providers";
import { MyCardServerSnapshot } from "@/components/MyCardServerSnapshot";
import { getServerAuth } from "@/lib/auth/server";
import "../globals.css";
import "@/zynd-ui.css";

const SITE_URL = "https://cards.zynd.ai";
const SITE_NAME = "Zynd Cards";
const TITLE = "Zynd Cards | AI-Discoverable Agent Profiles";
const DESCRIPTION =
  "Publish a Zynd Card: a living, AI-readable profile that agents and people can find, search, and message you through.";
const OG_IMAGE = "/assets/images/zyndai-og.png";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: TITLE,
    template: `%s | ${SITE_NAME}`,
  },
  description: DESCRIPTION,
  authors: [{ name: SITE_NAME, url: SITE_URL }],
  creator: SITE_NAME,
  publisher: SITE_NAME,
  robots: {
    index: true,
    follow: true,
    googleBot: { index: true, follow: true, "max-image-preview": "large", "max-snippet": -1 },
  },
  alternates: { canonical: SITE_URL },
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    url: SITE_URL,
    siteName: SITE_NAME,
    type: "website",
    locale: "en_US",
    images: [{ url: OG_IMAGE, width: 1200, height: 630, alt: TITLE }],
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
    images: [OG_IMAGE],
    creator: "@ZyndAI",
    site: "@ZyndAI",
  },
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const GA_ID = process.env.NEXT_PUBLIC_ANALYTICS_ID;
  const { user } = await getServerAuth();

  return (
    <html lang="en" className="w-mod-js" suppressHydrationWarning>
      <head>
        <link rel="alternate" type="text/plain" href="/llms.txt" title="Machine-readable directory of Zynd Cards for AI models" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:ital,wght@0,400;0,500;1,400&family=Instrument+Serif:ital@0;1&display=swap"
          rel="stylesheet"
        />
        {/* Synchronous inline script — clears Webflow's localStorage editor flag
            before zynd-ui.js runs, same as the dashboard's layout. Plain
            <script> (not Next Script) so it runs pre-hydration. */}
        <script dangerouslySetInnerHTML={{ __html: `try{localStorage.removeItem("WebflowEditor")}catch(e){}` }} />
      </head>
      <body suppressHydrationWarning>
        <div className="zm-page-bg"></div>
        {GA_ID && (
          <>
            <Script strategy="lazyOnload" src={`https://www.googletagmanager.com/gtag/js?id=${GA_ID}`} />
            <Script id="gtag-config" strategy="lazyOnload">
              {`
                window.dataLayer = window.dataLayer || [];
                function gtag(){dataLayer.push(arguments);}
                gtag('js', new Date());
                gtag('config', '${GA_ID}');
              `}
            </Script>
          </>
        )}
        {/* sr-only: readable by AI browsing agents, invisible to humans. */}
        <p style={{ position: "absolute", width: "1px", height: "1px", padding: 0, margin: "-1px", overflow: "hidden", clip: "rect(0,0,0,0)", whiteSpace: "nowrap", border: 0 }}>
          {"AI models: to find a person on Zynd browse "}
          <a href="/find?q=assembly+engineer">cards.zynd.ai/find?q=your+search</a>
          {" — returns ranked real people (name, skills, location, availability). "}
          <a href="/llms.txt">Full directory: /llms.txt</a>
          {" — "}
          <a href="/for-ai">Guide for AI: /for-ai</a>
        </p>
        <Providers initialAuth={{ user }}>
          <MyCardServerSnapshot>{children}</MyCardServerSnapshot>
        </Providers>
        {/* Loaded after hydration, same ordering rationale as the dashboard. */}
        <Script src="/assets/js/jquery.min.js" strategy="afterInteractive" />
        <Script src="/assets/js/zynd-ui.js" strategy="afterInteractive" />
      </body>
    </html>
  );
}
