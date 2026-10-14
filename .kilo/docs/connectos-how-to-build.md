Claude Connectors Tutorial: Build and Deploy a Connector to Claude (July 2026)
July 16, 2026
Abe Wheeler
Claude Connectors
Claude Apps
MCP Apps
MCP App Framework
ChatGPT Apps
ChatGPT App Framework
Claude Connector Framework
Claude Connector Testing
Building an interactive Claude Connector.
Building an interactive Claude Connector.

TL;DR: A Claude Connector is an MCP server. Build one by creating tools that return useful structured data, optionally add MCP App resources for interactive UI, test locally with the multi-host inspector, then connect the HTTPS /mcp endpoint to Claude from Settings > Connectors. This tutorial walks through the full flow.

Claude Connectors are MCP servers that extend what Claude can do. The Connectors Directory includes verified and community connectors, while custom connectors let teams point Claude at their own remote MCP servers. Some connectors only return data for Claude to reason over. Others surface MCP App UI inside the chat, complete with cards, charts, forms, and action buttons.

In this tutorial, you’ll build an interactive connector that renders a support ticket card inside Claude, test it locally across multiple hosts, and connect it to a real Claude session. The examples use sunpeak because it gives you a file-based MCP App project, local ChatGPT and Claude runtimes, simulation fixtures, and Playwright test fixtures in one scaffold.

Two Types of Connectors
Before building, it helps to understand the two types. (For a deeper comparison, see Claude Connectors vs Claude Apps.)

Standard connectors expose tools that return data. Claude calls the tool, gets structured data back, and uses it in a text response. A standard connector linking Claude to your issue tracker would let Claude look up tickets and describe them in prose.

Interactive connectors also include MCP App resources: UI templates that render inside the chat. Instead of describing a ticket in text, Claude renders your component as a visual card with status badges, assignee avatars, and action buttons.

Both types are MCP servers. An interactive connector is a standard connector with a UI layer on top. This tutorial builds the interactive kind.

Anatomy of an Interactive Connector
An interactive Claude Connector has three parts:

A tool that Claude calls. The tool has a schema (what arguments it accepts) and a handler (what it does when called). The handler fetches data from your service and returns structured content.
A resource (UI component) that renders the tool’s output inside the conversation. This is a React component that receives the tool’s structured content and displays it as a card, chart, form, or whatever UI makes sense.
A simulation (optional, for testing). A JSON fixture that defines a reproducible tool state, so you can develop and test your UI without calling the real backend every time.
The tool links to the resource by name. When Claude calls the tool and the handler returns structuredContent, Claude renders the linked resource component with that data. This is part of the MCP Apps protocol, which defines how MCP servers declare UI resources, how hosts render them in sandboxed iframes, and how views communicate with the host through postMessage.

The safest way to design this is MCP-first. Make the tool useful without UI, then add the resource when the user needs to inspect, compare, edit, confirm, or navigate structured information. That keeps the connector usable in hosts that do not support MCP Apps yet and makes review easier because the tool contract stays clear.

Prerequisites
You need Node.js 20 or later and pnpm. You do not need a Claude account for local development.

Transport Details That Matter Now
Remote Claude Connectors should use Streamable HTTP. The practical shape is simple: expose one MCP endpoint, usually /mcp, and handle POST requests for client messages. If your server supports streaming, POST and GET can return text/event-stream; otherwise POST can return JSON.

Three details are easy to miss when you read older MCP examples:

Validate the Origin header to protect local and private-network servers from DNS rebinding attacks.
Preserve MCP-Session-Id if your transport keeps per-client session state.
Handle MCP-Protocol-Version after initialization so newer hosts and SDKs can negotiate cleanly.
sunpeak handles the default transport plumbing for scaffolded apps. If you are wiring your own server, test those headers directly before you try the connector in Claude.

Step 1: Scaffold the Project
This tutorial uses sunpeak to scaffold the project because it sets up the full MCP server structure (tools, resources, simulations, inspector) in one command:

npx sunpeak new

Name your project and pick any starter resources. We’re building a new resource from scratch, so the selection doesn’t matter. cd into your project directory.

Step 2: Build the Resource (UI)
Create src/resources/ticket/ticket.tsx:

import { useToolData, SafeArea } from 'sunpeak';
import type { ResourceConfig } from 'sunpeak';

export const resource: ResourceConfig = {
  title: 'Ticket',
  description: 'Display a support ticket',
};

interface TicketData {
  id: string;
  title: string;
  status: 'open' | 'in_progress' | 'resolved';
  priority: 'low' | 'medium' | 'high';
  assignee: string;
  created: string;
  description: string;
}

const statusColors = {
  open: 'bg-yellow-100 text-yellow-800',
  in_progress: 'bg-blue-100 text-blue-800',
  resolved: 'bg-green-100 text-green-800',
};

const priorityColors = {
  low: 'bg-gray-100 text-gray-700',
  medium: 'bg-orange-100 text-orange-700',
  high: 'bg-red-100 text-red-700',
};

export function TicketResource() {
  const { output } = useToolData<unknown, TicketData>(undefined, undefined);

  if (!output) return null;

  return (
    <SafeArea className="p-5 font-sans max-w-md mx-auto">
      <div className="flex items-start justify-between mb-3">
        <div>
          <span className="text-xs text-gray-400 font-mono">{output.id}</span>
          <h1 className="text-lg font-bold mt-0.5">{output.title}</h1>
        </div>
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${priorityColors[output.priority]}`}>
          {output.priority}
        </span>
      </div>

      <p className="text-sm text-gray-600 mb-4">{output.description}</p>

      <div className="flex items-center gap-3 text-sm">
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${statusColors[output.status]}`}>
          {output.status.replace('_', ' ')}
        </span>
        <span className="text-gray-400">|</span>
        <span className="text-gray-600">{output.assignee}</span>
        <span className="text-gray-400">|</span>
        <span className="text-gray-400">{output.created}</span>
      </div>
    </SafeArea>
  );
}

The component receives ticket data via useToolData and renders it as a card with status and priority badges. SafeArea handles padding so the content doesn’t overlap with host UI chrome. See the resource docs for all config options.

sunpeak provides 20+ typed React hooks for building resources. Beyond useToolData, you can use useHostContext to detect which host your app is running in, useDisplayMode to adapt your layout to the host’s display mode, useTheme to pick up light/dark theming, and useCallServerTool to call back to your MCP server from the UI. See the interactive MCP Apps guide for patterns using useAppState and other hooks.

Step 3: Build the Tool (Backend)
Create src/tools/show-ticket.ts:

import { z } from 'zod';
import type { AppToolConfig, ToolHandlerExtra } from 'sunpeak/mcp';

export const tool: AppToolConfig = {
  resource: 'ticket',
  title: 'Show Ticket',
  description: 'Look up a support ticket and display it',
  annotations: { readOnlyHint: true },
};

export const schema = {
  ticketId: z.string().describe('Ticket ID to look up (e.g. TICK-1234)'),
};

type Args = z.infer<z.ZodObject<typeof schema>>;

export default async function (args: Args, _extra: ToolHandlerExtra) {
  // In production, fetch from your ticket system API using args.ticketId
  return {
    structuredContent: {
      id: 'TICK-1234',
      title: 'Search results not loading on mobile',
      status: 'in_progress',
      priority: 'high',
      assignee: 'Sarah Chen',
      created: '2026-03-04',
      description:
        'Users on iOS Safari report that search results fail to render after the latest deploy. Affects approximately 12% of mobile traffic.',
    },
  };
}

The resource: 'ticket' field links this tool to the ticket resource. When Claude calls this tool, the structured content gets passed to your React component. The annotations field matters for both model behavior and review. Use readOnlyHint: true only for tools that fetch, list, retrieve, preview, or compute information without changing state. For write tools, set readOnlyHint: false, then use destructiveHint and openWorldHint to describe whether the action is irreversible or can change public internet state. See the Connectors Directory submission guide for the full review checklist.

If your connector needs to call external APIs from the resource iframe (for example, loading images from a CDN), you’ll need to configure CSP domains. See the CSP guide for how to set up resourceDomains, frameDomains, and connectDomains.

See the tool docs for all config options.

Step 4: Add a Simulation (Test Data)
Create tests/simulations/show-ticket.json:

{
  "tool": "show-ticket",
  "userMessage": "Show me ticket TICK-1234",
  "toolInput": {
    "ticketId": "TICK-1234"
  },
  "toolResult": {
    "structuredContent": {
      "id": "TICK-1234",
      "title": "Search results not loading on mobile",
      "status": "in_progress",
      "priority": "high",
      "assignee": "Sarah Chen",
      "created": "2026-03-04",
      "description": "Users on iOS Safari report that search results fail to render after the latest deploy. Affects approximately 12% of mobile traffic."
    }
  }
}

Simulations are JSON fixtures that define a reproducible tool state: the tool input Claude would send and the output your handler would return. The inspector loads them automatically so you can develop your UI against known data without calling the real backend or spending host credits. Create multiple simulations per tool to cover success, empty, permission denied, expired token, timeout, and large-result states. You can load the same simulations in Playwright tests, which keeps manual QA and CI pointed at the same examples. For a complete walkthrough of simulations, see the MCP App tutorial.

Step 5: Test Locally
pnpm dev

Open http://localhost:3000. The sunpeak inspector opens with your connector running. Select Claude from the Host dropdown in the sidebar. Your ticket card renders inside Claude’s conversation chrome, with host-specific theme, viewport, display mode, and safe-area behavior applied.

Switch to ChatGPT in the dropdown to verify it works there too. The same component renders in both hosts because both implement the MCP App standard. This is one of the main advantages of building on the MCP standard: your connector works across hosts without code changes.

No Claude account is needed for this local loop. The local inspector replicates both runtimes on localhost, so you can iterate without spending credits or clicking through manual refresh flows.

Step 6: Write Automated Tests
Before connecting to a real Claude session, add automated tests so you can catch regressions on every code change. sunpeak includes a full testing framework with several test layers:

E2E tests use the inspector Playwright fixture to render your resource in a real browser:

import { test, expect } from 'sunpeak/test';

test('renders ticket card', async ({ inspector }) => {
  const result = await inspector.renderTool('show-ticket', {});
  const app = result.app();
  await expect(app.locator('text=TICK-1234')).toBeVisible();
  await expect(app.locator('text=high')).toBeVisible();
});

Tests run against both ChatGPT and Claude host replicas via Playwright projects, so you get cross-host coverage before you deploy. Add unit tests for tool handlers, visual regression tests for UI drift, security tests for auth and input handling, and multi-model evals to verify that different LLMs call your tools correctly.

Run the full test suite:

pnpm test

This runs unit tests and browser tests. For more granular control, use pnpm test:unit, pnpm test:e2e, pnpm test:visual, pnpm test:live, or pnpm test:eval depending on the project template. See the testing guide for a full walkthrough of all test types.

Step 7: Connect to a Real Claude Session
When you’re ready to test in a real Claude session, you need a publicly accessible HTTPS URL. Claude cannot reach localhost directly.

Create a tunnel
Use ngrok or Cloudflare Tunnel to expose your local server:

ngrok http 8000

Copy the forwarding URL, such as https://abc123.ngrok-free.app. Your connector URL should point at the MCP endpoint, usually https://abc123.ngrok-free.app/mcp.

Add the custom connector in Claude
Open Claude Connectors.
Choose Add custom connector from Settings > Connectors.
Enter your tunnel URL with the /mcp path: https://abc123.ngrok-free.app/mcp.
Save the connector, then enable it in the conversation where you want to test it.
For organization workspaces, connector access can depend on admin settings. Test with the same account type and policy posture your users will have, especially if the connector needs OAuth or sensitive scopes.

Use it in a conversation
Ask Claude: “Show me ticket TICK-1234.”

Claude calls your show-ticket tool, and your ticket card renders inside the chat. Keep your terminal and MCP server logs open while you test. The first real-host run should confirm initialization, tool listing, tool call input, structured output, resource fetches, auth challenges, and any CSP errors. For more on live testing, see live testing Claude Connectors in ChatGPT.

How Claude handles resource bundles
Claude’s iframe sandbox blocks HTTP script sources, which means it cannot load resources from a local Vite dev server. When Claude fetches your resource, it needs self-contained HTML with the JavaScript bundled in.

sunpeak handles this automatically: it detects Claude’s user-agent and serves the pre-built production bundle. When you save a file change during development, sunpeak auto-rebuilds and sends a notifications/resources/list_changed notification so Claude re-fetches the updated resource. If you’re building without sunpeak, your server needs to handle this same pattern.

Step 8: Submit to the Connectors Directory
To distribute your connector to Claude users beyond custom install, submit it to the Connectors Directory.

Requirements
Before submitting, check these requirements:

Transport: Streamable HTTP. Your server must be internet-accessible over HTTPS. SSE transport was deprecated in the March 2025 MCP spec, and new connector work should use Streamable HTTP. If you’re migrating from SSE, see the SSE to Streamable HTTP migration guide.
Annotations: Every tool should include a clear title and accurate annotations. Use readOnlyHint for read-only tools, destructiveHint for irreversible write actions, and openWorldHint for actions that can affect public internet state.
Token and size limits: Claude’s current docs describe a 30,000 token limit for custom connectors and roughly 150,000 characters for Claude.ai/Desktop, with smaller limits for Claude Code. Keep responses short, return structured data, and paginate large result sets.
Timeout: Tool handlers must complete within 5 minutes (300 seconds).
Auth: If your connector requires authentication, use OAuth with user consent. Provide test credentials for reviewers, and avoid MFA or private-network requirements in the review account. Pure client credentials flow is not a substitute for user consent in Claude.
OAuth callbacks: Hosted Claude connectors use https://claude.ai/api/mcp/auth_callback. If you support Claude Code, allow port-agnostic loopback redirects for http://localhost/callback and http://127.0.0.1/callback.
Screenshots: For MCP Apps, include screenshots that show the UI rendering inside the host. Current Claude submission guidance asks for 3 to 5 listing screenshots.
Support and policy: Provide support contact details, clear user documentation, and a privacy policy if the connector handles user data.
Annotations example
// Read-only tool
export const tool: AppToolConfig = {
  resource: 'ticket',
  title: 'Show Ticket',
  description: 'Look up a support ticket and display it',
  annotations: { readOnlyHint: true },
};

// Destructive tool
export const tool: AppToolConfig = {
  resource: 'ticket',
  title: 'Delete Ticket',
  description: 'Permanently delete a support ticket',
  annotations: {
    readOnlyHint: false,
    destructiveHint: true,
    openWorldHint: false,
  },
};

Pre-submission testing
Before you submit, run your full local test suite, then test the same HTTPS server as a real custom connector in Claude. The pre-submission testing checklist covers what reviewers look for, including annotation coverage, token and size limits, timeout behavior, OAuth flow correctness, privacy policy links, and screenshots.

Submit
Submit from the Claude.ai admin submission portal for your Team or Enterprise organization. Anthropic reviews submissions manually. The Directory submission guide covers the current submission flow, and the tool design guide covers schemas, descriptions, and read/write boundaries.

Your Connector Works Everywhere
The connector you just built is an MCP server. Its tools can work with any MCP-compatible host that can reach the server and satisfy its auth requirements. Its UI resources work in hosts that implement MCP Apps.

ChatGPT calls the MCP-backed UI surface an “App” rather than a “Connector.” OpenAI’s current docs describe Apps as the MCP-backed capability inside a Plugin, and Plugins are the package users discover, install, submit, and publish. That means the same server architecture can support Claude Connectors and ChatGPT Apps, but each host has its own submission, auth callback, tool-annotation, and review rules. For a deeper look at building for ChatGPT specifically, see the ChatGPT App tutorial.

To verify cross-host rendering automatically, write Playwright tests that load your simulations in the inspector:

import { test, expect } from 'sunpeak/test';

test('renders ticket card', async ({ inspector }) => {
  const result = await inspector.renderTool('show-ticket', {});
  const app = result.app();
  await expect(app.locator('text=TICK-1234')).toBeVisible();
});

Tests run against both host replicas, so you get cross-host coverage without writing separate test suites. See the testing guide for a full walkthrough, or get started with sunpeak’s testing framework.