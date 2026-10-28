import type { Metadata } from "next";

import { LegalLink, LegalList, LegalPage, LegalSection } from "@/components/LegalPage";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Zynd Companion",
  description:
    "A small browser extension that updates your Zynd card from the page you are on: what you are working on, and what you are exploring.",
  path: "/companion",
});

export default function CompanionPage() {
  return (
    <LegalPage title="Zynd Companion" updated="October 27, 2026">
      <p className="mb-10 leading-relaxed text-zinc-300">
        Zynd Companion is a browser extension for Chrome, Edge and Brave. It lets you set what you
        are working on and share what you are exploring, from the page you are already on, without
        opening your card. Nothing is sent until you press Add.
      </p>

      <LegalSection title="What it does">
        <LegalList>
          <li>
            <strong className="text-white">Working on.</strong> Type a line and it goes on top of
            the Working On section of your card.
          </li>
          <li>
            <strong className="text-white">Currently exploring.</strong> Open the extension on a
            repo, paper, video, post, newsletter, blog or news article. It fills in the title and
            guesses the kind; you check it and add it. It shows on your card for 30 days.
          </li>
          <li>
            <strong className="text-white">Take it back.</strong> Every line and link you add can
            be removed from the extension, and the extension asks before anything else.
          </li>
        </LegalList>
      </LegalSection>

      <LegalSection title="How it knows it is you">
        <p>
          The extension has no account of its own. You connect it from the extension, which opens
          this site; you sign in here if you are not already, and you confirm. After that it
          holds a token that works only for the two things above. It cannot read your messages,
          change your profile or settings, or publish anything else.
        </p>
        <p>
          You can disconnect any browser from the extension, or from the connect page while signed
          in. A browser that has not been used for 90 days has to be connected again.
        </p>
      </LegalSection>

      <LegalSection title="What it reads">
        <LegalList>
          <li>
            Only the page you are on, and only when you open the extension or choose{" "}
            <em>Clip to Zynd profile</em> from the right-click menu. It does not watch your
            browsing, keep a history or run in the background on other pages.
          </li>
          <li>
            It never sends a page on your own computer or private network (localhost, internal
            addresses, intranet names), and it removes tracking parameters from links.
          </li>
          <li>It does not run in private (incognito) windows.</li>
        </LegalList>
      </LegalSection>

      <LegalSection title="Help and policies">
        <p>
          <LegalLink href="/companion/connect">Connect or manage your browsers</LegalLink> &middot;{" "}
          <LegalLink href="/support">Support</LegalLink> &middot;{" "}
          <LegalLink href="/privacy">Privacy Policy</LegalLink>
        </p>
      </LegalSection>
    </LegalPage>
  );
}
