Build one remote MCP server and expose it as a connector/plugin to both ChatGPT and Claude. MCP is the shared integration layer: ChatGPT uses it for plugins/custom MCP apps, while Claude uses it for connectors across Claude web/Desktop/Code/API.

Architecture
text
User → ChatGPT / Claude
          ↓
   Remote MCP Server (HTTPS)
          ↓
   Your business API / database / SaaS
          ↓
   OAuth Authorization Server (Auth0, WorkOS, Entra, etc.)
Your MCP server is the resource server; your identity provider is the authorization server. ChatGPT and Claude are OAuth clients acting on behalf of the signed-in user.

What to build
Use the official MCP SDK (@modelcontextprotocol/sdk for TypeScript or the Python MCP SDK) and deploy a Streamable HTTP endpoint, e.g. https://mcp.yourapp.com/mcp. ChatGPT supports Streamable HTTP and SSE; Claude connectors use remote MCP servers.

Required MCP surface
Expose these MCP primitives:

MCP primitive	Purpose	Example
tools/list	Tool discovery	search_leads, create_task
tools/call	Execute an action	Create a CRM task
resources	Read-only context/data	Recent documents, records
prompts	Reusable prompt templates	“Summarize account health”
Tool annotations	Safety hints	readOnlyHint, destructiveHint
Keep tools narrow, typed, and action-oriented. Prefer search_orders, create_invoice, and get_profile over one vague do_action tool.

Recommended API/tool set
For a typical SaaS connector:

get_profile — returns the authenticated user/profile; important for multi-account support in ChatGPT.

search_* — read/search operations, e.g. search_documents, search_customers.

get_* — fetch a specific object by stable ID.

create_* / update_* — write operations; require explicit scopes.

delete_* — destructive operations; mark them with destructiveHint: true and require a narrow scope.

Optional webhooks/callback endpoint — for async workflows, but do not put tokens in URLs.

Tool schema example
ts
server.registerTool(
  "create_task",
  {
    title: "Create task",
    description: "Creates a task in the user's workspace.",
    inputSchema: {
      title: z.string(),
      due_date: z.string().optional(),
    },
    securitySchemes: [{ type: "oauth2", scopes: ["tasks:write"] }],
    annotations: {
      readOnlyHint: false,
      destructiveHint: false,
    },
  },
  async ({ title, due_date }, ctx) => {
    const user = await verifyAccessToken(ctx.authToken);
    const task = await api.createTask(user.id, title, due_date);
    return {
      content: [{ type: "text", text: JSON.stringify(task) }],
      structuredContent: task,
    };
  }
);
ChatGPT supports per-tool securitySchemes with noauth and oauth2; declare OAuth scopes on every privileged tool.

MCP spec requirements
Target the current MCP authorization model:

Serve protected-resource metadata at /.well-known/oauth-protected-resource.

Return 401 Unauthorized with a WWW-Authenticate header pointing to that metadata.

Publish OAuth authorization-server metadata at /.well-known/oauth-authorization-server or OIDC discovery.

Use authorization-code flow with PKCE S256.

Echo the resource parameter through authorization and token exchange, and bind it to the token audience.

Validate every incoming bearer token: signature, issuer, audience/resource, expiry, and scopes.

Protected resource metadata
json
{
  "resource": "https://mcp.yourapp.com",
  "authorization_servers": ["https://auth.yourapp.com"],
  "scopes_supported": ["profile:read", "tasks:read", "tasks:write"]
}
Claude requires the resource value to exactly match the MCP server URL users enter, and uses the first entry in authorization_servers.

Authorization server metadata
json
{
  "issuer": "https://auth.yourapp.com",
  "authorization_endpoint": "https://auth.yourapp.com/authorize",
  "token_endpoint": "https://auth.yourapp.com/token",
  "registration_endpoint": "https://auth.yourapp.com/register",
  "client_id_metadata_document_supported": true,
  "token_endpoint_auth_methods_supported": ["none", "private_key_jwt"],
  "code_challenge_methods_supported": ["S256"],
  "scopes_supported": ["profile:read", "tasks:read", "tasks:write"]
}
ChatGPT supports CIMD with none or private_key_jwt, and DCR when available. Claude supports DCR and CIMD; for CIMD, Claude requires client_id_metadata_document_supported: true and none in token_endpoint_auth_methods_supported.

OAuth and redirects
Use OAuth 2.1 authorization-code + PKCE. Do not use password grants, implicit flow, or machine-to-machine client_credentials for user-scoped connectors; neither ChatGPT nor Claude supports that pattern for per-user access.

Flow
User asks ChatGPT/Claude to use a protected tool.

Host calls your MCP server without a valid token.

Your server returns 401 plus WWW-Authenticate: Bearer resource_metadata="...".

Host discovers your authorization server and client-registration method.

Host opens the provider’s consent screen with PKCE.

User signs in and consents.

Provider redirects to the host’s registered callback.

Host exchanges the code for access and refresh tokens.

Host sends Authorization: Bearer <access_token> on MCP calls.

Your MCP server validates the token before executing the tool.

Redirect URIs to allowlist
Register these exact redirect URIs in your authorization server:

Client	Redirect URI
ChatGPT, without RFC 9207 issuer identification	https://chatgpt.com/connector/oauth/{callback_id}
ChatGPT, with issuer identification support	https://chatgpt.com/connector_platform_oauth_redirect
Claude hosted apps: web, Desktop, mobile, Cowork	https://claude.ai/api/mcp/auth_callback
Claude Code	Port-agnostic loopback: http://localhost/callback and http://127.0.0.1/callback
ChatGPT’s exact callback appears in its MCP server management page; copy it verbatim.

Redirect security
Allow only exact, pre-registered redirect URIs; never wildcard production callbacks.

Require HTTPS for non-loopback redirects.

Support RFC 9207 iss in authorization responses if you want ChatGPT’s stable redirect URI; the returned iss must exactly match your metadata issuer.

For Claude Code, match loopback redirects port-agnostically for both localhost and 127.0.0.1.

Token handling
Implement a shared auth middleware:

text
Authorization: Bearer <JWT/opaque token>
  → verify signature or introspect token
  → check iss
  → check aud / resource claim
  → check exp / nbf
  → check required scope
  → resolve user and tenant
  → execute tool with that identity
If verification fails, return:

text
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer resource_metadata="https://mcp.yourapp.com/.well-known/oauth-protected-resource", scope="tasks:write"
Claude refreshes tokens reactively after a 401 and proactively before expiry; return standards-compliant invalid_grant when a refresh token is dead, and rotate refresh tokens for public clients.

Making one build work on both
The compatibility strategy is:

Layer	Shared implementation	Platform-specific handling
MCP tools/resources	Same server, same tool names and schemas	None
Transport	Streamable HTTP	ChatGPT also accepts SSE
OAuth discovery	RFC 9728 + RFC 8414/OIDC metadata	Exact issuer/redirect behavior differs
Client registration	Prefer CIMD, with DCR fallback	Claude requires both CIMD flags for CIMD; ChatGPT supports none/private_key_jwt
Scopes	Same scope names and least privilege	Host may request OIDC scopes if advertised
Tool auth	Per-tool securitySchemes and runtime 401 challenge	ChatGPT uses _meta["mcp/www_authenticate"] for tool-level auth UI
For maximum compatibility, implement CIMD + DCR + PKCE S256 + RFC 9207 issuer identification + resource echo. That covers both platforms without maintaining separate MCP servers.

Registration steps
ChatGPT
Enable Developer Mode / custom MCP connector access in the workspace.

Go to ChatGPT Plugins or connector settings and choose Add custom MCP server.

Enter your public HTTPS MCP URL, such as https://mcp.yourapp.com/mcp.

Select OAuth and complete the authorization flow.

Run Scan Tools, install the plugin/app, and test tool calls in chat or Deep Research.

Claude
In Claude, open Customize → Connectors or Organization settings → Connectors.

Choose Add → Custom → Web.

Enter the remote MCP server URL.

Choose authentication: Sign in now, Sign in when needed, or No sign in.

Choose the OAuth client mode: Claude’s published identity, automatic registration, or your own OAuth client.

Add and test the connector.

Practical build checklist
Public HTTPS MCP endpoint at /mcp

Streamable HTTP transport

Typed tools with JSON Schema inputs/outputs

Read-only tools marked readOnlyHint

Dangerous tools marked destructiveHint

get_profile tool with stable opaque user ID

/.well-known/oauth-protected-resource

OAuth/OIDC discovery metadata

Authorization-code + PKCE S256

CIMD and/or DCR support

resource parameter echoed into token audience

Exact ChatGPT and Claude redirect URIs registered

Token verification middleware

Refresh-token rotation for public clients

Rate limits, audit logs, tenant isolation, and scope enforcement

The core rule: do not build separate “ChatGPT plugins” and “Claude plugins.” Build a secure, standards-compliant remote MCP server once; register its OAuth client/redirects separately for each host, then add the same URL in both ChatGPT and Claude.