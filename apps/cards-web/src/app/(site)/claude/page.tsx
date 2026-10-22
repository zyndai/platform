import type { Metadata } from "next";

import { LegalLink, LegalList, LegalPage, LegalSection } from "@/components/LegalPage";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "Zynd for Claude",
  description:
    "Connect Claude to your Zynd facts and public card: what the connector does, how to add it, and how saving and publishing stay in your hands.",
  path: "/claude",
});

const CODE = "rounded bg-white/10 px-1.5 py-0.5 font-mono text-sm text-[#a5b4fc]";

const TOOLS: { name: string; title: string; does: string }[] = [
  {
    name: "recall_memories",
    title: "Recall private facts",
    does: "Finds your private facts that match a search phrase (up to 500 characters) and returns at most 10. Read-only.",
  },
  {
    name: "propose_memory",
    title: "Propose a private fact",
    does: "Drafts one fact for you to review. It saves nothing.",
  },
  {
    name: "get_proposal_status",
    title: "Check proposal status",
    does: "Reports whether a proposal is pending, rejected, expired, saved privately or waiting to appear on your card. Read-only.",
  },
  {
    name: "list_pending_facts",
    title: "List pending card facts",
    does: "Lists your private card facts and open proposals, without publishing any of them. Read-only.",
  },
  {
    name: "propose_card_fact",
    title: "Propose a public card fact",
    does: "Drafts the public wording for one existing private fact so you can review it. It publishes nothing.",
  },
  {
    name: "get_public_card",
    title: "Show public card",
    does: "Returns only the facts already approved for your public card. Read-only.",
  },
];

export default function ClaudePage() {
  return (
    <LegalPage title="Zynd for Claude" updated="October 22, 2026">
      <p className="mb-10 leading-relaxed text-zinc-300">
        The Zynd connector lets Claude recall your private Zynd facts when you ask, show what is
        on your public card, and draft new facts for you to review. Claude can propose. Only you
        can save or publish, by signing in at cards.zynd.ai.
      </p>

      <LegalSection title="Add Zynd to Claude">
        <p>
          The connector address is{" "}
          <code className={CODE}>https://api.zynd.ai/claude/mcp</code>. You need a Zynd account
          first: create your card at <LegalLink href="/create">cards.zynd.ai</LegalLink>.
        </p>
        <LegalList>
          <li>
            <strong className="text-white">Claude on the web, desktop and mobile.</strong> Open
            Settings, then Connectors, then Add custom connector. Paste the address, then sign in
            to Zynd in the browser window that opens.
          </li>
          <li>
            <strong className="text-white">Claude Code.</strong> Run{" "}
            <code className={CODE}>
              claude mcp add --scope user --transport http zynd https://api.zynd.ai/claude/mcp
            </code>
            , type <code className={CODE}>/mcp</code> in Claude Code, and authorize{" "}
            <code className={CODE}>zynd</code> in your browser.
          </li>
        </LegalList>
        <p>
          The Zynd plugin bundles this connector with three skills (<code className={CODE}>zynd-context</code>,{" "}
          <code className={CODE}>zynd-memory</code> and <code className={CODE}>zynd-card</code>) that tell Claude
          when it may use it. It has no hooks, commands or agents.
        </p>
        <p>
          Zynd asks for exactly three permissions: recall your private facts, propose facts for
          your review, and review your card facts. It asks for nothing else, and you approve the
          sign-in yourself.
        </p>
      </LegalSection>

      <LegalSection title="What Claude can do">
        <LegalList>
          {TOOLS.map((tool) => (
            <li key={tool.name}>
              <strong className="text-white">{tool.title}</strong> (
              <code className={CODE}>{tool.name}</code>). {tool.does}
            </li>
          ))}
        </LegalList>
        <p>
          Claude uses these only when you ask. It does not read your Zynd facts at the start of a
          conversation, in the background, or because a task might benefit from them.
        </p>
      </LegalSection>

      <LegalSection title="How saving and publishing work">
        <LegalList>
          <li>
            A proposal is a temporary draft. Claude shows you its exact text and a link to
            cards.zynd.ai. Proposals expire after 24 hours.
          </li>
          <li>
            You open the link, sign in, and choose <em>Save privately</em> or, for a card fact,
            preview and confirm the exact public wording. A &ldquo;yes&rdquo; in the chat, or
            anything Claude sends, cannot do either.
          </li>
          <li>
            Saving privately does not publish. Each fact needs its own confirmation, and editing
            the wording needs a fresh one.
          </li>
          <li>
            Claude does not receive the confirmation code, and it is not asked to supply one.
          </li>
        </LegalList>
      </LegalSection>

      <LegalSection title="What it cannot do">
        <p>
          The connector cannot export or delete your data, edit your profile, message other
          people, make introductions, or publish anything for you. Please do not ask Claude to
          remember passwords, API keys or similar secrets; it is instructed not to propose them.
        </p>
      </LegalSection>

      <LegalSection title="Troubleshooting">
        <LegalList>
          <li>
            <strong className="text-white">&ldquo;No ZYND account found.&rdquo;</strong> Sign in
            with the account that owns your card, or create your card first, then connect again.
          </li>
          <li>
            <strong className="text-white">Claude does not offer the Zynd tools.</strong> Remove
            the connector, add it again with the address above, and complete the sign-in.
          </li>
          <li>
            <strong className="text-white">A proposal link says it expired or belongs to another
            account.</strong> Ask Claude for a new proposal, and review it while signed in to the
            account you connected.
          </li>
          <li>
            <strong className="text-white">Disconnect Claude.</strong> Sign in, open your card
            editor and choose the AI tab. You can disconnect Claude on its own or every assistant.
          </li>
        </LegalList>
      </LegalSection>

      <LegalSection title="Help and policies">
        <p>
          <LegalLink href="/support">Support</LegalLink> &middot;{" "}
          <LegalLink href="/privacy">Privacy Policy</LegalLink> &middot;{" "}
          <LegalLink href="/terms">Terms of Service</LegalLink>
        </p>
      </LegalSection>
    </LegalPage>
  );
}
