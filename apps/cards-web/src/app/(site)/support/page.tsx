import type { Metadata } from "next";

import { LegalLink, LegalList, LegalPage, LegalSection } from "@/components/LegalPage";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Support",
  description: "Get help with Zynd Cards and the Zynd assistant plugin, or remove your data.",
  path: "/support",
});

export default function SupportPage() {
  return (
    <LegalPage title="Support" updated="October 21, 2026">
      <LegalSection title="Contact us">
        <p>
          Email <LegalLink href="mailto:contact@zynd.ai">contact@zynd.ai</LegalLink> for help
          with Zynd Cards or the Zynd plugin, to report a problem, or to make a privacy
          request. Please do not include passwords or API keys in your message.
        </p>
        <p>Zynd AI Inc, 8 The Green STE A, Dover, DE 19901.</p>
      </LegalSection>

      <LegalSection title="Common tasks">
        <LegalList>
          <li>
            <strong className="text-white">Review or publish a proposed fact.</strong> Open
            the link the assistant gave you and sign in at cards.zynd.ai. Nothing is saved or
            published until you confirm there. Proposals expire after 24 hours.
          </li>
          <li>
            <strong className="text-white">Connect or disconnect an assistant.</strong> Sign
            in, open your card editor and choose the AI tab. You can disconnect one assistant
            or all of them.
          </li>
          <li>
            <strong className="text-white">Remove a fact or card content.</strong> Edit your
            card, or forget or dismiss the fact in the AI tab. Public content disappears from
            your card as soon as you remove it.
          </li>
          <li>
            <strong className="text-white">Erase your data.</strong> Email us from the address
            on your account and tell us what to delete: a fact, a record, or the whole account.
          </li>
        </LegalList>
      </LegalSection>

      <LegalSection title="Policies">
        <p>
          <LegalLink href="/privacy">Privacy Policy</LegalLink> &middot;{" "}
          <LegalLink href="/terms">Terms of Service</LegalLink>
        </p>
      </LegalSection>
    </LegalPage>
  );
}
