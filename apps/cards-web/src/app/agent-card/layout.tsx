import type { Metadata } from "next";
import "./agent-card.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://cards.zynd.ai"),
  title: "Zynd — The Living Professional Identity for Technical Builders and Agents",
  description:
    "Zynd synthesizes GitHub, LinkedIn, X and your website into one living professional profile — browsable by people, searchable by AI agents.",
  alternates: { canonical: "/agent-card" },
};

/**
 * Standalone root layout. `/agent-card` deliberately sits OUTSIDE the `(site)`
 * route group so it does not inherit globals.css / zynd-ui.css — the page ships
 * its own compiled Tailwind v3 stylesheet and would otherwise fight the app's
 * Tailwind 4 preflight.
 */
export default function AgentCardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="scroll-smooth bg-[#080909] text-[#bfbfb9]">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="bg-[#080909] text-[#d3d3cd] font-sans antialiased selection:bg-[#7b72e9] selection:text-black overflow-x-hidden tech-grid min-h-screen">
        {children}
      </body>
    </html>
  );
}
