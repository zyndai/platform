import type { Metadata } from "next";
import { EB_Garamond, JetBrains_Mono } from "next/font/google";
import "./dear.css";

const serif = EB_Garamond({ subsets: ["latin"], style: ["normal", "italic"], variable: "--font-serif", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: { default: "Dear Agent", template: "%s · Dear Agent" },
  description:
    "Your next collaborator won't Google you. Their agent will. Write the letter that tells every AI who you are today, and what it may do in your name.",
  // The new UI runs on example data until it is wired to the backend.
  robots: { index: false, follow: false },
};

/**
 * Root layout for the Dear Agent UI. It sits in its own route group so it
 * inherits none of the legacy stylesheets (globals.css, zynd-ui.css, the
 * landing page's compiled Tailwind) and can be reviewed side by side with the
 * live pages. Every route under it lives at /dear/… for now.
 */
export default function DearLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${serif.variable} ${mono.variable}`}>
      <body className="dear desk">{children}</body>
    </html>
  );
}
