import type { Metadata } from "next";
import { Inter } from "next/font/google";

import { GoogleTags } from "@/components/GoogleTags";
import { MyCardServerSnapshot } from "@/components/MyCardServerSnapshot";
import { Providers } from "@/components/providers";
import { getServerAuth } from "@/lib/auth/server";

import "./landing-v2.css";

const inter = Inter({ subsets: ["latin"], display: "swap" });

export const metadata: Metadata = {
  metadataBase: new URL("https://cards.zynd.ai"),
  title: "Zynd — Your Work Has a World Beyond Your Profile",
  description: "Turn what you build into a living identity, ready to be discovered by people and AI agents.",
  // Preview of the redesigned landing page; `/` stays canonical until it replaces it.
  alternates: { canonical: "/" },
  robots: { index: false, follow: true },
};

const CANVAS_WIDTH = 1440;

// Runs before first paint so narrow screens never flash the unscaled 1440px canvas.
const FIT_CANVAS_SCRIPT = `(function(){var d=document.documentElement;function f(){d.style.setProperty("--landing-v2-zoom",String(Math.min(1,d.clientWidth/${CANVAS_WIDTH})))}f();addEventListener("resize",f)})();`;

/**
 * Standalone root layout for the redesigned landing page. Like `(landing)`, it
 * sits outside `(site)` so it doesn't inherit the app's dark globals.css, and
 * seeds auth + my-card state server-side the same way so the signed-in CTA
 * paints without waiting for a client round-trip.
 */
export default async function LandingV2Layout({ children }: { children: React.ReactNode }) {
  const { user } = await getServerAuth();
  return (
    // FIT_CANVAS_SCRIPT writes the zoom variable onto <html> before React hydrates.
    <html lang="en" className={`${inter.className} scroll-smooth`} suppressHydrationWarning>
      <body className="bg-white text-[#262627] antialiased overflow-x-hidden">
        <script dangerouslySetInnerHTML={{ __html: FIT_CANVAS_SCRIPT }} />
        <Providers initialAuth={{ user }}>
          <MyCardServerSnapshot>{children}</MyCardServerSnapshot>
        </Providers>
        <GoogleTags />
      </body>
    </html>
  );
}
