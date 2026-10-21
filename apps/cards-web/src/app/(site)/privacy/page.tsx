import type { Metadata } from "next";

import { LegalLink, LegalList, LegalPage, LegalSection } from "@/components/LegalPage";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Privacy Policy",
  description:
    "What Zynd Cards and the Zynd assistant plugin store, who can see it, how long it is kept, and how to remove it.",
  path: "/privacy",
});

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy Policy" updated="October 21, 2026">
      <p className="mb-10 leading-relaxed text-zinc-300">
        Zynd AI Inc (&ldquo;Zynd,&rdquo; &ldquo;we,&rdquo; &ldquo;us&rdquo;), a Delaware
        corporation, runs Zynd Cards at cards.zynd.ai and the Zynd memory service at
        api.zynd.ai. This policy covers both, including the Zynd plugin that lets an AI
        assistant such as ChatGPT recall your facts and propose new ones. Persona
        (persona.zynd.ai) and the ZyndAI developer platform (zynd.ai) are separate products
        with their own policies.
      </p>

      <LegalSection title="1. The short version">
        <LegalList>
          <li>
            Only what you approve for your public card is public. Everything else stays
            private to you.
          </li>
          <li>
            An assistant can never publish or save for you. It can only propose, and you
            confirm on cards.zynd.ai while signed in.
          </li>
          <li>You can remove any fact or card content at any time.</li>
          <li>We do not sell your data and we do not show advertising.</li>
        </LegalList>
      </LegalSection>

      <LegalSection title="2. What we store">
        <LegalList>
          <li>
            <strong className="text-white">Account.</strong> You sign in with LinkedIn. We
            receive the name, email address and profile photo LinkedIn returns when you
            authorize it.
          </li>
          <li>
            <strong className="text-white">Your card.</strong> The headline, about text,
            skills, projects, links and other details you add or approve. The parts you
            publish are public; see section 3.
          </li>
          <li>
            <strong className="text-white">Private facts.</strong> Short facts about you
            (up to 2,000 characters each) that you or an assistant you authorized asked
            Zynd to remember. They are private until you approve one for your card.
          </li>
          <li>
            <strong className="text-white">Temporary proposals.</strong> When an assistant
            proposes a fact, we hold the proposed text as a draft for up to 24 hours so you
            can review it. Unreviewed drafts expire and are discarded automatically.
          </li>
          <li>
            <strong className="text-white">Decision records.</strong> When you save or
            publish a proposed fact, or reject it, we record which action it was, a
            one-way hash of the text, your decision, the result, the time, and which
            assistant connection created it.
          </li>
          <li>
            <strong className="text-white">Assistant connections.</strong> Which assistants
            you connected, the permissions you granted (recall facts, propose facts,
            review card facts), when you connected and when you disconnected.
          </li>
          <li>
            <strong className="text-white">Usage data.</strong> Product events such as card
            views, share clicks and publishing steps, kept with a hashed session identifier
            and a coarse browser type rather than your name. The website also uses Google
            Analytics for aggregate traffic statistics, which sets cookies.
          </li>
        </LegalList>
        <p>
          When an assistant uses the plugin, Zynd receives only what the assistant sends in
          that one request: a search phrase of up to 500 characters, or the text of one
          proposed fact. We do not receive your conversation history.
        </p>
        <p>
          Please do not ask Zynd to remember passwords, API keys, payment card numbers,
          government identifiers or medical records. The plugin tells assistants not to
          propose them.
        </p>
      </LegalSection>

      <LegalSection title="3. What is public">
        <p>
          A fact or card detail becomes public only when you approve that exact wording for
          your card on cards.zynd.ai. Saving a fact privately, queueing it for review, or
          agreeing in a chat does not make it public. Public card content can be seen by
          anyone, including search engines and AI systems, and may be copied by others
          while it is public.
        </p>
        <p>
          The plugin can read your public card and your private facts when you ask the
          assistant to, and returns them only to that assistant in your chat.
        </p>
      </LegalSection>

      <LegalSection title="4. How we use it">
        <LegalList>
          <li>To show your card, find you in search and let people contact you through it.</li>
          <li>To answer recall requests you make through an assistant.</li>
          <li>To show you proposals for review and to record your decisions.</li>
          <li>To keep the service secure, prevent abuse and fix problems.</li>
          <li>To understand, in aggregate, how the product is used.</li>
        </LegalList>
        <p>We do not use your private facts for advertising or sell them.</p>
      </LegalSection>

      <LegalSection title="5. Who receives it">
        <LegalList>
          <li>
            <strong className="text-white">The public,</strong> for the card content you
            publish.
          </li>
          <li>
            <strong className="text-white">The assistant you connected.</strong> Whatever
            Zynd returns to an assistant becomes part of your conversation with it and is
            handled under that provider&rsquo;s own terms and privacy policy (for example,
            OpenAI for ChatGPT).
          </li>
          <li>
            <strong className="text-white">Service providers</strong> that run our
            infrastructure on our behalf: our database and sign-in provider (Supabase),
            our hosting providers, and Google Analytics for site statistics.
          </li>
          <li>
            <strong className="text-white">Model providers,</strong> for other Zynd
            features that process text you add to memory (for example, extracting facts from
            content you provide). Today these are OpenAI for embeddings and DeepSeek for
            fact extraction. Facts you save through the plugin are stored as written and
            are not sent to them by the plugin&rsquo;s tools.
          </li>
          <li>
            <strong className="text-white">Authorities,</strong> when the law requires it.
          </li>
        </LegalList>
      </LegalSection>

      <LegalSection title="6. How long we keep it and how to remove it">
        <LegalList>
          <li>
            <strong className="text-white">Proposals</strong> expire after 24 hours.
          </li>
          <li>
            <strong className="text-white">Card content and private facts</strong> stay
            until you remove them. You can edit or remove card content, dismiss a pending
            fact, or forget a stored fact at any time. A removed fact stops appearing on
            your card and stops being returned to assistants straight away.
          </li>
          <li>
            <strong className="text-white">Permanent erasure.</strong> Removing a fact in
            the app makes it inactive. To have a fact, a decision record or your whole
            account erased from our systems, email{" "}
            <LegalLink href="mailto:contact@zynd.ai">contact@zynd.ai</LegalLink> and we will
            delete it.
          </li>
          <li>
            <strong className="text-white">Assistant connections</strong> can be
            disconnected at any time, one at a time or all at once. A disconnected assistant
            stops working immediately. We keep the record that it was connected.
          </li>
          <li>
            <strong className="text-white">Usage events</strong> are deleted after 180 days.
          </li>
        </LegalList>
      </LegalSection>

      <LegalSection title="7. Your choices">
        <p>
          Sign in to cards.zynd.ai, open your card editor and use the AI tab to review
          pending facts, approve or dismiss them, and connect or disconnect assistants. You
          can also remove the connection from inside the assistant. To access, correct or
          delete your data, email{" "}
          <LegalLink href="mailto:contact@zynd.ai">contact@zynd.ai</LegalLink>. We aim to
          reply within 30 days.
        </p>
      </LegalSection>

      <LegalSection title="8. Security">
        <p>
          Traffic to Zynd uses HTTPS. An assistant can only do what you permitted when you
          connected it, and it cannot save or publish anything without your separate
          confirmation on the website. No system is perfectly secure, so please keep
          secrets out of your facts.
        </p>
      </LegalSection>

      <LegalSection title="9. Children">
        <p>
          Zynd is not directed to children under 13 and we do not knowingly collect their
          data. If you believe a child has given us information, email us and we will delete
          it.
        </p>
      </LegalSection>

      <LegalSection title="10. International use">
        <p>
          Zynd is operated from the United States and our providers may process data in
          other countries.
        </p>
      </LegalSection>

      <LegalSection title="11. Changes">
        <p>
          If we change this policy in a material way we will update the date above and, where
          we can, tell you through the product or by email.
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
