"use client";

import { useState } from "react";
import Image from "next/image";
import { Bot, Download, HelpCircle, Network, Search, Sparkles, X } from "lucide-react";
import type { OwnerStatus } from "@/lib/owner-home";
import "./agent-traffic.css";

type Agent = NonNullable<OwnerStatus["activity"]["agent_clients"]>[number];
const FILTERS = ["All clients", "MCP", "Crawlers", "AI clients"] as const;
type Filter = typeof FILTERS[number];

function clientType(name: string): Filter | "Unknown" {
  if (name.endsWith("-MCP")) return "MCP";
  if (name === "Unknown") return "Unknown";
  if (["ChatGPT-User", "Claude-User", "Codex"].includes(name)) return "AI clients";
  return "Crawlers";
}

function providerTone(provider: string): string {
  if (/OpenAI/.test(provider)) return "openai";
  if (provider === "Claude") return "claude";
  if (provider === "Perplexity") return "perplexity";
  if (provider === "Amazon") return "amazon";
  if (provider === "Google") return "google";
  return "neutral";
}

function providerIcon(provider: string): string | null {
  const tone = providerTone(provider);
  return ["openai", "claude", "perplexity", "google"].includes(tone) ? `/assets/agents/${tone}.svg` : null;
}

function exportCsv(agents: Agent[]) {
  const csv = [["Provider", "Client", "Type", "Requests"], ...agents.map(agent =>
    [agent.provider, agent.name, clientType(agent.name), String(agent.count)])]
    .map(row => row.map(value => `"${value.replaceAll('"', '""')}"`).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "zynd-agent-traffic-7-days.csv";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function AgentTraffic({ clients }: { clients: OwnerStatus["activity"]["agent_clients"] }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("All clients");
  const agents = [...(clients ?? [])].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  const total = agents.reduce((sum, agent) => sum + agent.count, 0);
  const search = query.trim().toLowerCase();
  const visible = agents.filter(agent => (filter === "All clients" || clientType(agent.name) === filter)
    && `${agent.provider} ${agent.name}`.toLowerCase().includes(search));
  const providers = new Set(agents.filter(agent => agent.name !== "Unknown" && agent.name !== "Zynd-MCP").map(agent => agent.provider));

  return (
    <section className="oh-agent-traffic oh-discovery-history" aria-labelledby="agent-clients">
      <header className="oh-agent-header">
        <div className="oh-agent-heading">
          <span className="oh-agent-emblem"><Sparkles size={19} aria-hidden="true" /></span>
          <div><span className="oh-agent-eyebrow">PROFILE DISCOVERY</span><h3 id="agent-clients">Which agents visited</h3></div>
        </div>
        <div className="oh-agent-window"><span>Latest 1,000</span><span>Last 7 days</span></div>
      </header>
      <p className="oh-agent-description">Reported client identities, not verified model names. Older requests without a saved client name appear as Unknown.</p>

      {clients != null && <div className="oh-agent-summary">
        <span><strong>{total.toLocaleString("en-US")}</strong> recorded requests</span>
        <span><strong>{agents.length.toLocaleString("en-US")}</strong> client identities</span>
        <span><strong>{providers.size.toLocaleString("en-US")}</strong> named providers</span>
      </div>}

      {!!agents.length && <div className="oh-agent-toolbar">
        <label className="oh-agent-search">
          <Search size={15} aria-hidden="true" />
          <input aria-label="Search agent traffic" placeholder="Search providers or clients…" value={query} onChange={event => setQuery(event.target.value)} />
          {query && <button type="button" aria-label="Clear agent search" onClick={() => setQuery("")}><X size={14} aria-hidden="true" /></button>}
        </label>
        <button className="oh-agent-export" type="button" onClick={() => exportCsv(visible)} disabled={!visible.length}>
          <Download size={14} aria-hidden="true" />Export CSV
        </button>
      </div>}

      {!!agents.length && <div className="oh-agent-filters" role="group" aria-label="Filter agent traffic">
        {FILTERS.map(value => <button type="button" key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>
          {value}<span>{value === "All clients" ? agents.length : agents.filter(agent => clientType(agent.name) === value).length}</span>
        </button>)}
      </div>}

      {visible.length ? <ul className="oh-agent-list">
        {visible.map(agent => {
          const type = clientType(agent.name);
          const share = total ? agent.count / total * 100 : 0;
          const Icon = type === "MCP" ? Network : type === "Unknown" ? HelpCircle : Bot;
          const logo = providerIcon(agent.provider);
          return <li className="oh-agent-row" key={agent.name} data-tone={providerTone(agent.provider)}>
            <span className="oh-agent-avatar">{logo ? <Image src={logo} alt="" width={22} height={22} aria-hidden="true" /> : <Icon size={20} aria-hidden="true" />}</span>
            <div className="oh-agent-identity">
              <div className="oh-agent-name"><span>{agent.provider}</span><span className="oh-agent-type">{type === "AI clients" ? "AI client" : type === "Crawlers" ? "Crawler" : type === "Unknown" ? "Legacy record" : "MCP"}</span></div>
              <code>{agent.name}</code>
            </div>
            <div className="oh-agent-share" aria-label={`${share.toFixed(1)}% of requests in this breakdown`}>
              <span>{share.toFixed(1)}% of requests</span>
              <div aria-hidden="true"><i style={{ width: `${share}%` }} /></div>
            </div>
            <span className="oh-agent-count">{agent.count.toLocaleString("en-US")} {agent.count === 1 ? "request" : "requests"}</span>
          </li>;
        })}
      </ul> : <div className="oh-agent-empty">
        <Bot size={26} aria-hidden="true" />
        <p>{clients == null ? "Agent breakdown is unavailable." : agents.length ? "No clients match your filters." : "No AI clients recorded in the last 7 days."}</p>
        {!!agents.length && <button type="button" onClick={() => { setQuery(""); setFilter("All clients"); }}>Clear filters</button>}
      </div>}

      <footer className="oh-agent-footer">
        <span><i aria-hidden="true" />{visible.length} of {agents.length} client identities shown</span>
        <span>Counts cover the latest 1,000 recorded AI requests.</span>
      </footer>
    </section>
  );
}
