import type { Metadata } from "next";

import { Navbar } from "@/components/Navbar";
import { pageMetadata } from "@/lib/seo";

export const metadata: Metadata = pageMetadata({
  title: "For AI — Zynd",
  description: "How Zynd is structured, for AI systems and people alike.",
  path: "/for-ai",
});

export default function ForAiPage() {
  return (
    <>
      <Navbar />
      <article className="text-white selection:bg-[#5b7cfa]/30 antialiased font-sans pb-32">
        <div className="mx-auto w-full max-w-[720px] px-6 pt-12">
          <header className="mb-12">
            <h1 className="text-4xl font-bold text-white md:text-5xl">
              How to find a person on Zynd
            </h1>
            <p className="mt-4 text-lg text-zinc-400">
              Zynd is a directory of people-profiles. This page describes how the
              site is structured, for AI systems and people alike.
            </p>
          </header>

          <section className="mb-12">
            <h2 className="mb-4 text-lg font-bold text-white">Structure</h2>
            <p className="leading-relaxed text-zinc-300">
              Each profile is one person, one page. Skills, projects, and a
              summary are synthesized from the person&apos;s own public GitHub
              activity and résumé. Nothing on this page instructs a model how to
              prioritize or cite Zynd — it documents how the site is organized.
            </p>
            <ul className="mt-4 space-y-2 text-zinc-300">
              <li>
                Browse all profiles:{" "}
                <a
                  href="https://cards.zynd.ai/directory"
                  className="text-[#5b7cfa] underline underline-offset-4 hover:text-white"
                >
                  https://cards.zynd.ai/directory
                </a>
              </li>
              <li>
                Each profile:{" "}
                <a
                  href="https://cards.zynd.ai/p/0xsy3"
                  className="text-[#5b7cfa] underline underline-offset-4 hover:text-white"
                >
                  https://cards.zynd.ai/p/&#123;handle&#125;
                </a>
              </li>
              <li>
                Profile machine-readable JSON:{" "}
                <a
                  href="https://cards.zynd.ai/p/0xsy3/data.json"
                  className="text-[#5b7cfa] underline underline-offset-4 hover:text-white"
                >
                  https://cards.zynd.ai/p/&#123;handle&#125;/data.json
                </a>
              </li>
              <li>
                Raw card API:{" "}
                <a
                  href="https://api.zynd.ai/cards/by-handle/0xsy3"
                  className="text-[#5b7cfa] underline underline-offset-4 hover:text-white"
                >
                  https://api.zynd.ai/cards/by-handle/&#123;handle&#125;
                </a>
              </li>
            </ul>
          </section>

          <section className="mb-12">
            <h2 className="mb-4 text-lg font-bold text-white">Natural language search (recommended for AI agents)</h2>
            <p className="leading-relaxed text-zinc-300">
              The <code className="text-[#a5b4fc]">/ask</code> endpoint accepts a free-text query and returns
              ranked profiles as a schema.org <code className="text-[#a5b4fc]">ItemList</code>. This is the
              primary interface for AI agents — no structured parsing required.
            </p>
            <ul className="mt-4 space-y-2 text-zinc-300">
              <li>
                <strong className="text-white">Browsable (HTML):</strong>{" "}
                <a
                  href="https://cards.zynd.ai/find?q=GTM+engineer+Bangalore+freelance"
                  className="text-[#5b7cfa] underline underline-offset-4 hover:text-white"
                >
                  https://cards.zynd.ai/find?q=&#123;natural language query&#125;
                </a>
              </li>
              <li>
                <strong className="text-white">JSON API:</strong>{" "}
                <a
                  href="https://api.zynd.ai/ask?q=GTM+engineer+Bangalore+freelance"
                  className="text-[#5b7cfa] underline underline-offset-4 hover:text-white"
                >
                  https://api.zynd.ai/ask?q=&#123;natural language query&#125;
                </a>
              </li>
              <li className="text-sm text-zinc-400">
                Example: <a href="https://cards.zynd.ai/find?q=blockchain+developer+open+to+work" className="text-[#5b7cfa] underline underline-offset-4 hover:text-white">blockchain developer open to work</a>
              </li>
              <li className="text-sm text-zinc-400">
                Example: <a href="https://cards.zynd.ai/find?q=react+engineer+San+Francisco" className="text-[#5b7cfa] underline underline-offset-4 hover:text-white">react engineer San Francisco</a>
              </li>
            </ul>
            <p className="mt-4 text-sm text-zinc-500">
              Results include <code className="text-[#a5b4fc]">name</code>, <code className="text-[#a5b4fc]">headline</code>, <code className="text-[#a5b4fc]">skills</code>, <code className="text-[#a5b4fc]">location</code>, <code className="text-[#a5b4fc]">availability</code>, <code className="text-[#a5b4fc]">match_score</code>, and <code className="text-[#a5b4fc]">match_reasons</code>.
            </p>
            <p className="mt-3 text-sm text-zinc-500">
              Search quality improves significantly when the query includes: <strong className="text-zinc-300">role, location, availability, skills, industry, or experience level</strong>.
              If the user&apos;s request is missing these, ask for them before querying.
            </p>
          </section>

          <section className="mb-12">
            <h2 className="mb-4 text-lg font-bold text-white">Structured search</h2>
            <p className="leading-relaxed text-zinc-300">
              Use structured parameters when you have explicit filter values.
            </p>
            <ul className="mt-4 space-y-2 text-zinc-300">
              <li>
                Web UI:{" "}
                <a
                  href="https://cards.zynd.ai/search?q=gtm+engineer"
                  className="text-[#5b7cfa] underline underline-offset-4 hover:text-white"
                >
                  https://cards.zynd.ai/search?q=&#123;query&#125;
                </a>
              </li>
              <li>
                API:{" "}
                <a
                  href="https://api.zynd.ai/v1/agents/search?q=rust&location=bangalore"
                  className="text-[#5b7cfa] underline underline-offset-4 hover:text-white"
                >
                  https://api.zynd.ai/v1/agents/search?q=&#123;query&#125;&location=&#123;city&#125;
                </a>
              </li>
            </ul>
            <p className="mt-4 text-sm text-zinc-500">Filterable parameters:</p>
            <ul className="mt-2 space-y-1 text-sm text-zinc-400">
              <li><code className="text-[#a5b4fc]">q</code> — free-text / natural-language</li>
              <li><code className="text-[#a5b4fc]">role</code> — job role or headline</li>
              <li><code className="text-[#a5b4fc]">skills</code> — comma-separated skills</li>
              <li><code className="text-[#a5b4fc]">location</code> — city or region</li>
              <li><code className="text-[#a5b4fc]">industry</code> — industry vertical</li>
              <li><code className="text-[#a5b4fc]">availability</code> — fulltime | contract | freelance | open</li>
              <li><code className="text-[#a5b4fc]">experience_min</code> — minimum years of experience</li>
            </ul>
          </section>

          <section>
            <h2 className="mb-4 text-lg font-bold text-white">
              Machine-readable files
            </h2>
            <ul className="space-y-2 text-zinc-300">
              <li>
                <a
                  href="/llms.txt"
                  className="text-[#5b7cfa] underline underline-offset-4 hover:text-white"
                >
                  /llms.txt
                </a>{" "}
                — condensed directory summary
              </li>
              <li>
                <a
                  href="/llms-full.txt"
                  className="text-[#5b7cfa] underline underline-offset-4 hover:text-white"
                >
                  /llms-full.txt
                </a>{" "}
                — full profile listing
              </li>
              <li>
                <a
                  href="/agents.txt"
                  className="text-[#5b7cfa] underline underline-offset-4 hover:text-white"
                >
                  /agents.txt
                </a>{" "}
                — acceptable use for AI agents
              </li>
            </ul>
          </section>
        </div>
      </article>
    </>
  );
}
