A ChatGPT connector is a remote MCP server that ChatGPT reaches over HTTPS. Model Context Protocol (MCP) is the open standard that describes those calls, so once the connector is added, ChatGPT can invoke your tools and read your data inside a conversation.

This guide covers the whole path, from the packages you need through the route handler, authorization, deployment, and the validation flow in ChatGPT. It uses the mcp-handler package, Vercel's framework-agnostic HTTP adapter for MCP servers.

Copy link to headingWhat you need to build a ChatGPT MCP server
Five things have to be in place before the connector will add:

A Vercel project: Next.js works out of the box, as does any framework that exposes Web-standard Request and Response, including Nuxt, SvelteKit, and Hono.
Node.js 20 or later: Earlier versions won't run mcp-handler 2.x, which is the release this guide uses throughout.
The MCP packages: mcp-handler 2.x pairs with @modelcontextprotocol/server v2 and zod 4, and the three versions have to move together.
A ChatGPT account with developer mode: You add and test the connector there, and availability depends on your account and workspace policy.
An OAuth authorization server: Only needed if your tools read private data on behalf of a signed-in user.
If you'd rather start from working code, the MCP server template and the ChatGPT app template are both ready to deploy.

Copy link to headingHow ChatGPT connects to a remote MCP server
ChatGPT is a remote client, so it never launches your server as a subprocess the way a local editor does. It sends HTTP requests to a public HTTPS endpoint that speaks Streamable HTTP, conventionally at /mcp. If the server runs on a private network or a laptop, use Secure MCP Tunnel rather than exposing it.

At connection time, ChatGPT reads the tool names, descriptions, schemas, and annotations that your server advertises, then decides which tool to call based on a user's prompt. It captures that metadata once, when you create the connection, which matters later when you switch tools.

The 2026-07-28 MCP specification removes protocol-level sessions and the initialize handshake, so every request now carries its own protocol version and capabilities and can land on any instance. The specification also adds Mcp-Method and Mcp-Name headers, so a load balancer can route without parsing the request body.

Statelessness lines up with how Vercel Functions already work. mcp-handler 2.x serves the 2026-07-28 specification natively and falls back to stateless Streamable HTTP for 2025-era clients from the same handler, so a single route covers both generations. The older HTTP+SSE transport, which held a connection open with Server-Sent Events (SSE), is removed in 2.x, and Redis is no longer a dependency.

Copy link to headingHow to deploy an MCP server for ChatGPT on Vercel
Four steps take you from an empty route to a deployed endpoint.

Copy link to heading1. Install the packages
Add the adapter, the SDK server package, and Zod:

npm install mcp-handler @modelcontextprotocol/server zod
Version 2.x depends on @modelcontextprotocol/server, which is the SDK v2 package installed above. The older 1.x line depends on @modelcontextprotocol/sdk instead, where releases before 1.26.0 carry a known security vulnerability, so pin 1.26.0 or later if you stay on 1.x.

Copy link to heading2. Create the route handler
createMcpHandler returns a Web-standard request handler. Mount it in a Next.js route and export it for both methods:

app/api/mcp/route.ts
import { createMcpHandler } from "mcp-handler";
import { z } from "zod";

const handler = createMcpHandler((server) => {
  server.registerTool(
    "roll_dice",
    {
      title: "Roll Dice",
      description: "Roll a dice with a specified number of sides.",
      inputSchema: z.object({
        sides: z.number().int().min(2),
      }),
    },
    async ({ sides }) => {
      const value = 1 + Math.floor(Math.random() * sides);
      return {
        content: [{ type: "text", text: `You rolled a ${value}.` }],
      };
    },
  );
});

export { handler as GET, handler as POST };
The /api/mcp path is a convention rather than a requirement. mcp-handler doesn't inspect the pathname, so you can mount the handler on any route and give clients that route's full URL.

Copy link to heading3. Test the server locally
Run MCP Inspector against your dev server before ChatGPT ever sees it:

npx @modelcontextprotocol/inspector@latest
In the inspector, select Streamable HTTP, enter http://localhost:3000/api/mcp, then click Connect and List Tools. Exercise each tool with real inputs, missing identifiers, and empty results so schema and error handling are settled early.

Copy link to heading4. Deploy to Vercel
Push to Git or deploy with the Vercel CLI:

npx vercel deploy --prod
Your server is now reachable at the deployment URL plus the route, such as https://my-mcp-server.vercel.app/api/mcp. Keep that full URL, including the path, for the connection step.

Copy link to headingWhy Fluid compute fits MCP server traffic
That endpoint is already running on Fluid compute, which is enabled by default for projects created after April 23, 2025\. An MCP server spends most of its life idle, then handles short bursts of messages while waiting on databases and model APIs, which is the traffic shape it's built for.

Instead of one isolated instance per invocation, multiple invocations share the same instance. In-memory state and open connections survive between requests, and existing capacity absorbs new connections before Vercel scales out.

Billing follows the same idea. You pay $0.128 per hour of Active CPU and $0.0106 per GB-hour of Provisioned Memory in the default region. CPU accrues only while your code runs, memory accrues while a request is in flight, and nothing accrues between requests. Regional rates differ, so check Functions pricing for the region you deploy to.

Deploying the connector on Vercel brings the rest of the platform with it:

Instant Rollback: Use an instant rollback to revert to a previous production deployment if a tool change breaks a client.
Preview deployments: Point ChatGPT at a preview URL to test tool changes before production, with Deployment Protection keeping it private.
Vercel Firewall: Apply multi-layered protection to an endpoint that is public by necessity.
Rolling Releases: Roll a new version out to a fraction of traffic before promoting it.
Vercel runs its own MCP server on this stack, and you can connect ChatGPT to Vercel to manage projects and deployments from a conversation. With the server running, the remaining work is the tools it exposes.

Copy link to headingHow to add search and fetch to a ChatGPT MCP server
A connector no longer requires either tool to be added, but deep research and company knowledge both retrieve through that read-only pair, so ship both if either surface matters to you.

The search tool takes a query string and returns result objects carrying id, title, and url. The fetch tool takes one of those identifiers and returns the full document.

Return the same value twice, as structuredContent and as a JSON-encoded string in the content array:

app/api/mcp/route.ts
server.registerTool(
  "search",
  {
    title: "Search",
    description: "Search documents and return matching results.",
    inputSchema: z.object({ query: z.string() }),
  },
  async ({ query }) => {
    const results = await searchDocuments(query);
    return {
      structuredContent: { results },
      content: [{ type: "text", text: JSON.stringify({ results }) }],
    };
  },
);
The deep research template implements both tools end to end against a vector store.

Copy link to headingHow to add OAuth authorization to your MCP server
Tools that read private data need a signed-in user, and MCP's HTTP layer handles that with OAuth 2.1 semantics. mcp-handler covers the resource-server side, so you verify tokens and point clients at your authorization server instead of implementing the specification yourself.

Wrap the handler with withMcpAuth and supply a token verifier:

app/api/mcp/route.ts
import { createMcpHandler, withMcpAuth } from "mcp-handler";

const handler = createMcpHandler(/* tool registration from the route handler step */);

const verifyToken = async (req: Request, bearerToken?: string) => {
  if (!bearerToken) return undefined;

  // Replace with a call to your authorization server.
  const isValid = bearerToken === "your_access_token_here";
  if (!isValid) return undefined;

  return {
    token: bearerToken,
    scopes: ["read:stuff"],
    clientId: "your_client_id_here",
  };
};

const authHandler = withMcpAuth(handler, verifyToken, {
  required: true,
  requiredScopes: ["read:stuff"],
  resourceMetadataPath: "/.well-known/oauth-protected-resource",
});

export { authHandler as GET, authHandler as POST };
Unauthenticated requests now get a 401 with a challenge that points at your protected resource metadata, which the client reads to find your authorization server.

Serve that document from a second route:

app/.well-known/oauth-protected-resource/route.ts
import {
  protectedResourceHandler,
  metadataCorsOptionsRequestHandler,
} from "mcp-handler";

const handler = protectedResourceHandler({
  authServerUrls: ["<https://your-authorization-server.example.com>"],
});

const corsHandler = metadataCorsOptionsRequestHandler();

export { handler as GET, corsHandler as OPTIONS };
The 2026-07-28 specification deprecates Dynamic Client Registration in favor of Client ID Metadata Documents, where a client identifies itself with an HTTPS URL that serves its own metadata.

Your authorization server advertises and implements that support, not your MCP server. Check whether your provider offers it before you build around registration. The authorization guide has the full wiring.

Copy link to headingHow to connect and test your ChatGPT connector
With the server deployed, ChatGPT's own connection flow doubles as your validation harness.

Turn on developer mode first:

Open Settings.
Select Security and login.
Turn on Developer mode.
Availability depends on your account and workspace policy, so the toggle may be absent on some plans.

Then add the server:

Go to ChatGPT Plugins.
Select the plus button.
Enter a user-facing name and description.
Under Connection, enter your MCP server URL, including the /mcp path.
Create the connection.
Review the tools and metadata discovered from the server.
If the tools you expect appear in that list, transport and tool discovery both work. Start a new conversation and add the connection from the tools menu. Run prompts that should call a specific tool alongside prompts that shouldn't call anything, so you catch over-eager tool selection early.

Copy link to headingHow to troubleshoot a ChatGPT connector that fails
Most failures here are silent. The connector doesn't add, or a tool stops appearing, with no error text to work from.

Work through these causes in order:

ChatGPT can't reach the server: The endpoint has to be public HTTPS, and the URL has to include the route path. Confirm the same URL works in MCP Inspector, or use Secure MCP Tunnel for a private server.
Updated tools don't appear: Metadata is captured when the connection is created. Deploy the change, open the connection in ChatGPT Plugins, select Refresh, then start a new conversation.
The build breaks after upgrading to 2.x: server.tool() is now registerTool, inputSchema takes a full schema such as z.object({ ... }) instead of a raw Zod shape, and basePath, disableSse, redisUrl, maxDuration, and sessionIdGenerator are gone. Mount the handler at the route you want, rather than configuring paths.
Older SSE clients drop off: The HTTP+SSE transport from 2024-11-05 is removed in 2.x. Stay on mcp-handler 1.x until those clients migrate.
The function times out while streaming: A streaming response can keep a function open with no work being done. Set maxDuration per function and send data during real work instead of going silent.
OAuth fails partway through sign-in: A person needs time to finish a browser flow. Confirm /.well-known/oauth-protected-resource resolves in production and lists the correct authorization server.
Set the duration ceiling explicitly rather than inheriting the default. On Pro and Enterprise, raise it on the MCP route alone:

{
  "$schema": "<https://openapi.vercel.sh/vercel.json>",
  "functions": {
    "app/api/mcp/route.ts": { "maxDuration": 800 }
  }
}
With Fluid compute, every plan defaults to 300 seconds. Hobby is capped there, so the setting above has no effect on a Hobby project. Values above 800 seconds are in beta and need per-function configuration on supported Node.js and Python versions.

If a connection needs to pause and resume across minutes or months, Vercel Workflows is the better fit than a longer ceiling.

Copy link to headingNext steps
Once the connector validates in ChatGPT, the same server works with any MCP client that speaks Streamable HTTP. Start a new Vercel project for your server, or browse the templates to begin from a working MCP implementation.

Copy link to headingRelated resources
Deploy MCP servers to Vercel
MCP on Vercel
Fluid compute
Configuring function duration
Vercel MCP server
Build an MCP server with Express
Copy link to headingFrequently asked questions
Copy link to headingDo I need search-and-fetch tools for a ChatGPT connector?
No, not anymore. Neither tool is required to add a connector, so a server without them still works in chat. It stays inert in deep research and company knowledge, which retrieve only through that pair. If you want those surfaces, name the tools exactly search and fetch and keep both read-only.

Copy link to headingDoes my MCP server need to be public for ChatGPT to use it?
Yes for a normal connection, and again at submission. ChatGPT connects to remote servers via a public HTTPS endpoint, so it can't connect to a laptop or a private network. Secure MCP Tunnel covers private servers during development, but it doesn't replace the public endpoint required for plugin submission.

Copy link to headingWhy doesn't my ChatGPT connector show my updated tools?
Metadata is captured when the connection is created, so a redeploy alone changes nothing. Open the connection in ChatGPT Plugins and select Refresh. Published plugins behave differently, running on reviewed metadata snapshots, so updating those means scanning the server, submitting a new version, and publishing the approved one.

Copy link to headingDo I still need Redis to run an MCP server on Vercel?
No. mcp-handler 2.x dropped the transport that needed shared session state, and the 2026-07-28 specification removed protocol-level sessions. State that has to survive across calls now lives in your application, as a handle your tool mints and returns for the model to pass back as an ordinary argument.

Copy link to headingWhat is the maximum function duration for a streaming MCP server?
With Fluid compute, every plan defaults to 300 seconds. Hobby is capped there, while Pro and Enterprise reach 800 seconds, and values above that are in beta and set per function. A function that runs past its ceiling returns a 504 with FUNCTION_INVOCATION_TIMEOUT. For longer pauses, use Vercel Workflows.