import type { Metadata } from "next";
import Link from "next/link";
import { Footer, TopBar } from "@/components/dear/ui";

export const metadata: Metadata = { title: "For agents" };

const TOOLS = [
  ["find_people(query)", "Ranked letters with the lines that matched and when each was approved. Letters nobody has claimed are left out unless you ask for them."],
  ["read_letter(handle)", "One letter: every inked line with its source, the date it was last true, and how to cite it."],
  ["ask_letter(handle, question)", "An answer built only from inked lines. If the letter does not cover it, the answer says so."],
  ["say_hello(handle, who, why, asks)", "Carries a request to the owner. Needs your identity. The owner approves or declines; nothing is shared before that."],
];

const SAMPLE = `{
  "name": "Meera Iyer",
  "as_of": "2026-10-08",
  "cite_as": "Meera Iyer, Dear Agent, as of 2026-10-08",
  "agent": "zns:meera.9f4a",
  "claimed": true,
  "lines": [
    {
      "kind": "building",
      "text": "An identity card that AI agents can read and people can trust",
      "source": "written by them",
      "also_in": ["github"],
      "approved_at": "2026-10-08"
    },
    {
      "kind": "looking_for",
      "text": "A founding engineer who has shipped payments or identity",
      "approved_at": "2026-10-02",
      "expires_at": "2026-11-01"
    }
  ],
  "may": { "speak_for_me": true, "find_people": true, "hire_agents": false },
  "always_ask_first": ["introductions", "meetings", "anything that costs money"]
}`;

/**
 * The page an agent, or the person building one, lands on (slices S06, S11).
 * It replaces "for-ai", the unstyled /find, and the llms.txt that inlined
 * every person on every request.
 */
export default function ForAgents() {
  return (
    <div className="shell narrow">
      <TopBar current="/dear/for-agents" />
      <header className="stack">
        <p className="m glow">If you are an agent, or building one</p>
        <h1 className="display" style={{ fontSize: "clamp(40px, 6vw, 64px)" }}>
          How to read a letter.
        </h1>
        <p className="lede">Every line a person approved, with its source and its date. Nothing they did not approve. One thing you may do, and it needs their yes.</p>
      </header>

      <section className="stack">
        <h2 className="h2">Three rules</h2>
        <div className="rows">
          <p style={{ fontSize: 23 }}>Say only what is in ink. If the letter does not cover it, say that, and do not guess.</p>
          <p style={{ fontSize: 23 }}>Say when. Every line carries the date it was approved. Quote it: “as of 8 October”.</p>
          <p style={{ fontSize: 23 }}>Ask first. You may carry a hello to someone. You may not promise anything in their name.</p>
        </div>
      </section>

      <section className="stack">
        <h2 className="h2">What a letter looks like to you</h2>
        <pre className="code">{SAMPLE}</pre>
        <p className="dim">
          Try it:{" "}
          <Link href="/dear/l/meera-iyer/data.json" className="glow">
            /dear/l/meera-iyer/data.json
          </Link>
        </p>
      </section>

      <section className="stack">
        <h2 className="h2">Connect over MCP</h2>
        <pre className="code">{`{ "mcpServers": { "dear-agent": { "url": "https://api.zynd.ai/mcp" } } }`}</pre>
        <div className="scroll">
          <table style={{ borderCollapse: "collapse", width: "100%", minWidth: 520 }}>
            <tbody>
              {TOOLS.map(([name, what]) => (
                <tr key={name} style={{ borderBottom: "1px solid var(--line)" }}>
                  <td className="mono glow" style={{ padding: "12px 16px 12px 0", verticalAlign: "top", whiteSpace: "nowrap" }}>
                    {name}
                  </td>
                  <td style={{ padding: "12px 0" }}>{what}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel stack">
        <h2 className="h3">No MCP? Plain HTTP works.</h2>
        <dl className="kv">
          <dt>Search</dt>
          <dd className="mono">GET /ask?q=…</dd>
          <dt>One letter</dt>
          <dd className="mono">GET /dear/l/&#123;handle&#125;/data.json</dd>
          <dt>Index</dt>
          <dd className="mono">GET /llms.txt · a short index that points here, not a dump of every person</dd>
        </dl>
      </section>

      <Footer />
    </div>
  );
}
