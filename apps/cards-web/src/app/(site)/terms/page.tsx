import type { Metadata } from "next";

import { LegalLink, LegalList, LegalPage, LegalSection } from "@/components/LegalPage";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Terms of Service",
  description: "The terms for using Zynd Cards and the Zynd assistant plugin.",
  path: "/terms",
});

export default function TermsPage() {
  return (
    <LegalPage title="Terms of Service" updated="October 21, 2026">
      <LegalSection title="1. Acceptance">
        <p>
          These terms are an agreement between you and Zynd AI Inc (&ldquo;Zynd,&rdquo;
          &ldquo;we,&rdquo; &ldquo;us&rdquo;), a Delaware corporation. By using Zynd Cards at
          cards.zynd.ai, the Zynd memory service, or the Zynd plugin for AI assistants (the
          &ldquo;Service&rdquo;), you agree to them and to our{" "}
          <LegalLink href="/privacy">Privacy Policy</LegalLink>. If you do not agree, do not
          use the Service.
        </p>
      </LegalSection>

      <LegalSection title="2. The Service">
        <p>
          Zynd Cards lets you keep a private memory of facts about yourself and publish a
          public card made from the facts you choose. The Zynd plugin lets an AI assistant
          you connect recall your facts, show your public card and your pending facts, and
          propose a new fact. A proposal is only a draft. It is saved or published only when
          you confirm it yourself on cards.zynd.ai.
        </p>
      </LegalSection>

      <LegalSection title="3. Your account and connections">
        <LegalList>
          <li>You sign in with LinkedIn and must give accurate information.</li>
          <li>
            You are responsible for activity under your account and for the assistants you
            connect to it. Disconnect any assistant you no longer trust from the AI tab of
            your card editor.
          </li>
          <li>You must be at least 13 years old to use the Service.</li>
        </LegalList>
      </LegalSection>

      <LegalSection title="4. Your content and your public card">
        <p>
          You keep ownership of what you provide. You give Zynd a limited licence to store,
          process and display it as needed to run the Service for you. Content you approve
          for your public card is visible to anyone, and Zynd may show it in search, in the
          directory and to AI systems while it is public. You can remove content at any time,
          and the licence for that content ends when it is removed, apart from copies made by
          others while it was public.
        </p>
        <p>
          You are responsible for what you save and publish, and you confirm that you have the
          right to share it.
        </p>
      </LegalSection>

      <LegalSection title="5. Acceptable use">
        <p>You agree not to:</p>
        <LegalList>
          <li>
            Impersonate another person, or publish information about someone else without
            their consent.
          </li>
          <li>
            Store passwords, API keys, payment card numbers, government identifiers or
            medical records in Zynd.
          </li>
          <li>Publish unlawful, harassing, deceptive or infringing content, or send spam.</li>
          <li>
            Try to bypass the confirmation step, forge confirmations, probe or disrupt the
            Service, or reverse-engineer it.
          </li>
        </LegalList>
      </LegalSection>

      <LegalSection title="6. Third-party services and AI assistants">
        <p>
          You sign in through LinkedIn and may use Zynd through assistants such as ChatGPT.
          Those services are not ours and are governed by their own terms and privacy
          policies. When Zynd returns information to an assistant, the assistant&rsquo;s
          provider receives it as part of your conversation.
        </p>
      </LegalSection>

      <LegalSection title="7. AI output">
        <p>
          Assistants and other AI features can be wrong. Check any fact before you rely on it
          or publish it. Zynd does not guarantee that anything an assistant says about you is
          accurate.
        </p>
      </LegalSection>

      <LegalSection title="8. Disclaimer and limitation of liability">
        <p>
          THE SERVICE IS PROVIDED &ldquo;AS IS&rdquo; WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
          IMPLIED. TO THE MAXIMUM EXTENT PERMITTED BY LAW, ZYND SHALL NOT BE LIABLE FOR ANY
          INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL OR PUNITIVE DAMAGES ARISING FROM YOUR
          USE OF THE SERVICE. ZYND DOES NOT GUARANTEE THAT THE SERVICE WILL BE UNINTERRUPTED
          OR ERROR-FREE.
        </p>
      </LegalSection>

      <LegalSection title="9. Ending your use">
        <p>
          You can stop at any time by disconnecting your assistants, removing your content, or
          asking us to delete your account at{" "}
          <LegalLink href="mailto:contact@zynd.ai">contact@zynd.ai</LegalLink>. We may suspend
          or end access for violations of these terms. Sections that by their nature should
          survive, including 4 (as to others&rsquo; copies), 8 and 11, do.
        </p>
      </LegalSection>

      <LegalSection title="10. Changes">
        <p>
          We may update these terms. If a change is material we will update the date above and,
          where we can, tell you through the product or by email. Continuing to use the Service
          after a change means you accept it.
        </p>
      </LegalSection>

      <LegalSection title="11. Governing law">
        <p>
          These terms are governed by the laws of the State of Delaware, without regard to its
          conflict-of-law rules.
        </p>
      </LegalSection>

      <LegalSection title="12. Contact">
        <p>
          Zynd AI Inc, 8 The Green STE A, Dover, DE 19901 &middot;{" "}
          <LegalLink href="mailto:contact@zynd.ai">contact@zynd.ai</LegalLink> &middot;{" "}
          <LegalLink href="/support">Support</LegalLink>
        </p>
      </LegalSection>
    </LegalPage>
  );
}
