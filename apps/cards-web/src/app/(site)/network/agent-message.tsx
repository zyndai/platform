"use client";

import { memo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

// Card assistant replies are model output, so they get markdown. Human
// messages never come through here: they stay plain text (see
// renderMessageContent in network-v2.tsx).

// Same pattern renderMessageContent uses for @handle highlighting.
const MENTION_SPLIT = /((?<![\w.])@[A-Za-z0-9_.-]{1,64})/;

type MdNode = { type: string; value?: string; children?: MdNode[]; data?: object };

function mentionNode(handle: string): MdNode {
  // An emphasis node rendered as <span class="nv2-mention"> via hName.
  return {
    type: "emphasis",
    data: { hName: "span", hProperties: { className: ["nv2-mention"] } },
    children: [{ type: "text", value: handle }],
  };
}

function splitText(value: string): MdNode[] {
  const nodes: MdNode[] = [];
  value.split("\n").forEach((line, lineIndex) => {
    // A soft line break renders as a space in markdown. The old plain-text
    // bubble kept every newline, so keep them: a reply without markdown
    // should look exactly like it did before.
    if (lineIndex > 0) nodes.push({ type: "break" });
    line.split(MENTION_SPLIT).forEach((part, partIndex) => {
      if (!part) return;
      nodes.push(partIndex % 2 === 1 ? mentionNode(part) : { type: "text", value: part });
    });
  });
  return nodes;
}

function chatify(node: MdNode) {
  // Link text stays as written; a mention highlight inside a link is noise.
  if (!node.children || node.type === "link" || node.type === "linkReference") return;
  const next: MdNode[] = [];
  for (const child of node.children) {
    if (child.type === "text" && child.value != null) {
      next.push(...splitText(child.value));
    } else {
      chatify(child);
      next.push(child);
    }
  }
  node.children = next;
}

function remarkChat() {
  return (tree: MdNode) => chatify(tree);
}

const components: Components = {
  a({ href, children }) {
    // The default URL transform already empties unsafe protocols such as
    // javascript:, which leaves nothing to link to.
    if (!href) return <span>{children}</span>;
    return <a href={href} target="_blank" rel="noopener noreferrer nofollow">{children}</a>;
  },
  img({ src, alt }) {
    // Never load remote images from model output: that is a tracking pixel
    // and a data-exfiltration channel. Show what the image was instead.
    const label = alt || "image";
    return typeof src === "string" && src
      ? <a href={src} target="_blank" rel="noopener noreferrer nofollow">{label}</a>
      : <span>{label}</span>;
  },
  table({ children }) {
    return <div className="nv2-md-scroll"><table>{children}</table></div>;
  },
};

const remarkPlugins = [remarkGfm, remarkChat];

export const AgentMarkdown = memo(function AgentMarkdown({ content }: { content: string }) {
  return (
    <div className="nv2-md">
      <ReactMarkdown remarkPlugins={remarkPlugins} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
});

/**
 * One Card assistant reply. `own` is the viewer's own assistant, shown on the
 * viewer's side with its own bubble style; the caller adds the label above.
 * Kept separate from the human bubble so the agent-only parts (markdown now,
 * streaming and sources later) have one place to live.
 */
export const AgentBubble = memo(function AgentBubble({
  content,
  own = false,
  pending = false,
  remembered = false,
}: {
  content: string;
  own?: boolean;
  pending?: boolean;
  remembered?: boolean;
}) {
  return (
    <div className={`nv2-bubble is-agent${own ? " is-own" : ""}${pending ? " is-pending" : ""}${remembered ? " is-remembered" : ""}`}>
      <AgentMarkdown content={content} />
    </div>
  );
});

/**
 * Inbox preview text without the inline markdown syntax. The database already
 * collapses a preview to one line, so block markers (list dashes, quotes) can
 * no longer be told from punctuation and are left alone; headings, emphasis,
 * code and links are what make a raw preview look broken.
 */
export function plainPreview(content: string): string {
  return content
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/(^|\s)#{1,6}\s+(?=\S)/g, "$1")
    .replace(/(\*\*|__|~~)(.+?)\1/g, "$2")
    .replace(/(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])/g, "$1")
    .replace(/`+([^`]*)`+/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}
