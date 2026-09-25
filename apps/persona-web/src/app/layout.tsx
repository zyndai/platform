import type { Metadata } from "next";
import { GoogleAnalytics } from "@next/third-parties/google";
import { Chakra_Petch, Fraunces, Geist, Geist_Mono, Instrument_Sans, Playfair_Display, Space_Grotesk } from "next/font/google";
import "./globals.css";

const fraunces = Fraunces({
  subsets: ["latin"],
  weight: ["300", "400", "500"],
  style: ["normal", "italic"],
  variable: "--font-fraunces",
  display: "swap",
});

const geist = Geist({
  subsets: ["latin"],
  weight: ["300", "400", "500"],
  variable: "--font-geist",
  display: "swap",
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
  weight: ["400"],
  variable: "--font-geist-mono",
  display: "swap",
});

const instrumentSans = Instrument_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-instrument-sans",
  display: "swap",
});

const playfairDisplay = Playfair_Display({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  style: ["normal", "italic"],
  variable: "--font-playfair",
  display: "swap",
});

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-space-grotesk",
  display: "swap",
});

const chakraPetch = Chakra_Petch({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-chakra-petch",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://persona.zynd.ai"),
  title: {
    default: "ZyndAI — Your AI Networking Agent",
    template: "%s · ZyndAI",
  },
  description:
    "Your Persona finds people worth meeting, reaches out on your behalf, and books the times. You just show up.",
  keywords: [
    "AI agent",
    "networking",
    "personal AI",
    "meeting scheduling",
    "professional networking",
    "AI persona",
    "automated outreach",
  ],
  robots: {
    index: true,
    follow: true,
  },
  openGraph: {
    type: "website",
    siteName: "ZyndAI",
    title: "ZyndAI — Your AI Networking Agent",
    description:
      "Your Persona finds people worth meeting, reaches out on your behalf, and books the times. You just show up.",
    url: "https://persona.zynd.ai",
    locale: "en_US",
  },
  twitter: {
    card: "summary_large_image",
    title: "ZyndAI — Your AI Networking Agent",
    description:
      "Your Persona finds people worth meeting, reaches out on your behalf, and books the times. You just show up.",
  },
  alternates: {
    canonical: "/",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${fraunces.variable} ${geist.variable} ${geistMono.variable} ${instrumentSans.variable} ${playfairDisplay.variable} ${spaceGrotesk.variable} ${chakraPetch.variable}`}
    >
      <head>
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              "@context": "https://schema.org",
              "@type": "WebSite",
              name: "ZyndAI",
              url: "https://persona.zynd.ai",
              description:
                "Your Persona finds people worth meeting, reaches out on your behalf, and books the times.",
              potentialAction: {
                "@type": "SearchAction",
                target: {
                  "@type": "EntryPoint",
                  urlTemplate: "https://persona.zynd.ai/p/{userId}",
                },
                "query-input": "required name=userId",
              },
            }),
          }}
        />
        <link
          rel="preload"
          as="image"
          href="/hero-bg.webp"
          type="image/webp"
          fetchPriority="high"
        />
        <script
          dangerouslySetInnerHTML={{
            __html: `
              try {
                var t = localStorage.getItem('zynd-theme');
                document.documentElement.setAttribute('data-theme', t === 'dark' ? 'dark' : 'light');
              } catch (_) {
                document.documentElement.setAttribute('data-theme', 'light');
              }
            `,
          }}
        />
      </head>
      <body suppressHydrationWarning>{children}</body>
      <GoogleAnalytics gaId={process.env.NEXT_PUBLIC_GA_ID || "G-1L9YDBKGRT"} />
    </html>
  );
}
