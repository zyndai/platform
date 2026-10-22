from urllib.parse import urlsplit

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The old hardcoded default. Never valid in production: any process that boots
# with this value (or no value at all) in a production environment is refused.
_DEV_JWT_SECRET = "dev-jwt-secret-change-me-in-production-0123456789"


class Settings(BaseSettings):
    """Runtime config, loaded from environment / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql://zynd:zynd@localhost:5433/zynd"
    redis_url: str = "redis://localhost:6380"

    # Offline mock embed/extract for local dev (no API keys, no spend).
    mock_llm: bool = False

    # Embeddings — OpenAI text-embedding-3-small, 1536 dims (brief: matches vector(1536)).
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"

    # Extraction — DeepSeek V3 via its OpenAI-compatible endpoint.
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    extraction_model: str = "deepseek-chat"

    # Dev auth — a shared bearer that maps to the dev user. Kept alongside the
    # M2 JWT path for local testing; never enable in production.
    dev_bearer_token: str = "dev-secret"
    dev_user_email: str = "dev@zynd.local"
    # Off by default so the shared dev backdoor token is NEVER honored in production.
    # Enable only in local/test envs (ENABLE_DEV_BEARER=true).
    enable_dev_bearer: bool = False

    # S01 — inferred facts stay private until the owner approves them.
    # On by default. Set FEATURE_S01_PRIVATE_DEFAULT=false to restore the old
    # "findability predicates are public on insert" behaviour (rollback).
    feature_s01_private_default: bool = True

    # S09 — per-assistant MCP tokens, scopes, and the cards toolset.
    # Off restores the single personal token (minting a new one revokes the old).
    feature_s09_mcp_clients: bool = True

    # S02 — after a memory-side public-card mutation (agent forget, /me/findability
    # approve/revoke/declare), fire-and-forget a cards-api snapshot refresh so the
    # public page/data.json update within seconds instead of waiting for the cron.
    # Off by default (rollback = leave off); enable FEATURE_S02_CARD_SYNC=true.
    feature_s02_card_sync: bool = False

    # S05 — typed MCP capture: tools/skills/projects map to predicates directly
    # instead of English → LLM extraction. Off by default (rollback = leave off).
    feature_s05_typed_capture: bool = False
    # When typed capture is off, still run quality scoring and log what would
    # be grouped/dropped (observe / flag-only). Ignored once typed capture is on
    # (quality then always runs and enforces soft triage).
    feature_s05_observe: bool = True

    # Memory quality (docs/plans/ZYND_MEMORY_QUALITY_PLAN.md). All off by default so a deploy
    # changes nothing until an operator opts in; dev enables them in its compose file.
    # Phase 1: /me/context + get_my_context rank by relevance and freshness and take a topic.
    feature_ranked_context: bool = False
    # Phase 2: every fact write goes through facts.write_fact (one fact per thing).
    feature_fact_families: bool = False
    # Phase 3: stricter extraction prompt and the second-sighting rule for inferred tech.
    feature_strict_tech: bool = False
    # Cards networking F4: find_people matches the target against individual public facts
    # (top 3 per person, current-state predicates weighted up) instead of one averaged
    # profile vector. Off = the previous cluster-vector ranking.
    feature_fact_matching: bool = False
    # Cards networking A2: results who have no claimed Card can be invited to claim one
    # (next_action invite_to_claim, tool invite_to_claim). Needs Cards' FEATURE_A2_INVITE_TO_CLAIM
    # and packages/db migration 0024. Off by default.
    feature_invite_to_claim: bool = False
    # Phase 4: last_seen_at / mention_count / base_confidence, idempotent decay, stale facts
    # never auto-archived. Needs feature_fact_families too (see Settings.freshness_v2). Turn on
    # ONLY after sql/schema.sql has been applied to the database (the columns must exist).
    feature_freshness_v2: bool = False

    # S11 — public Cards MCP (no auth) at /cards-public-mcp. Off by default;
    # mount + Caddy route when ready. Rollback: leave false / remove Caddy handle.
    feature_s11_public_mcp: bool = False
    # Internal cards-api base (compose: http://cards:8000; single-box: :8002).
    cards_api_base_url: str = "http://cards:8000"
    cards_site_base_url: str = "https://cards.zynd.ai"
    s11_rate_limit_per_minute: int = 60
    s11_get_card_cache_ttl_seconds: int = 60
    s11_max_response_bytes: int = 256_000

    # M2 — JWT + OAuth (dev-grade; see docs/CHATGPT_PLUGIN.md security notes).
    # Empty by default: production must set a strong random value (openssl rand -hex 32)
    # or the boot guard below refuses to start.
    jwt_secret: str = ""
    jwt_issuer: str = "zynd"
    # Shared secret for service-to-service endpoints (e.g. /v1/service/*) called
    # by zynd-cards. Empty = endpoint disabled.
    memory_service_token: str = ""
    # Explicit shared Supabase issuer for UUID-only S12 identity checks.
    # Empty keeps the bridge disabled; legacy email links are never used here.
    s12_identity_issuer: str = ""
    feature_s12_intros: bool = False
    # S10 owner read tools use the same cards aggregation over service HTTP.
    feature_s10_home: bool = False
    cards_api_url: str = "https://cards.api.zynd.ai"
    # MCP transport mode. Stateless (default) keeps the existing POST+DELETE
    # contract with no session IDs. Set true to re-enable the GET SSE stream for
    # clients that open a server-to-client connection (Kilo, Antigravity);
    # stateful mode requires session IDs on POSTs.
    feature_stateful_mcp: bool = False
    access_token_ttl_seconds: int = 3600
    refresh_token_ttl_seconds: int = 30 * 24 * 3600
    mcp_token_ttl_seconds: int = 90 * 24 * 3600   # long-lived token pasted into MCP clients
    # Public base URL of the MCP server (where clients connect). Used by the
    # MCP RemoteAuthProvider to advertise OAuth discovery endpoints. If the MCP
    # server runs on a different host/port than the API, set this explicitly.
    mcp_public_base_url: str = "http://localhost:8090"
    oauth_client_id: str = "zynd-chatgpt"
    oauth_client_secret: str = "zynd-oauth-secret"
    # Reserved public PKCE client. Empty callbacks keep it disabled until review setup.
    plugin_oauth_client_id: str = "zynd-chatgpt-plugin"
    plugin_oauth_redirect_uris: str = ""
    feature_plugin_consent: bool = False
    plugin_mcp_public_base_url: str = "http://localhost:8091/chatgpt"
    # Claude plugin: same six tools on their own resource. Claude brings its own
    # client_id (CIMD URL or DCR), so the grant is keyed on this resource, not a client.
    feature_claude_plugin: bool = False
    claude_plugin_mcp_public_base_url: str = "http://localhost:8092/claude"
    # Comma-separated email(s) of the sample-data account given to OpenAI's plugin
    # reviewers (email+password Supabase user). Empty disables the reviewer path.
    # Those sessions are accepted only by the plugin OAuth flow and plugin review
    # endpoints; supabase_identity() denies them everywhere else.
    plugin_review_emails: str = ""
    # Second confidential client: the Hermes Deployer. It runs the same
    # authorize-code flow as ChatGPT but, at /oauth/token, receives a long-lived
    # personal token (mcp_token_ttl_seconds) so a deployed agent container can
    # ingest continuously without refresh plumbing. Secret MUST be overridden in
    # prod via DEPLOYER_OAUTH_CLIENT_SECRET.
    deployer_oauth_client_id: str = "hermes-deployer"
    deployer_oauth_client_secret: str = "change-me-deployer-oauth-secret"
    # Comma-separated allowlist of redirect_uri prefixes (prevents open redirect).
    oauth_allowed_redirect_prefixes: str = (
        "https://chat.openai.com/aip/,https://chatgpt.com/aip/,"
        "https://chat.openai.com/connector/,https://chatgpt.com/connector/,"
        "https://chatgpt.com/connector_platform_oauth_redirect,"
        "https://claude.ai/api/mcp/,"
        "http://localhost,http://127.0.0.1"
    )
    # Deployer callback origins allowed as redirect_uri (merged into the allowlist
    # below). The deployer sends the browser to
    # https://<deployer>/api/agents/<id>/zynd/callback after sign-in.
    deployer_allowed_redirect_prefixes: str = (
        "https://deployer.zynd.ai/,http://localhost:3100/,http://127.0.0.1:3100/"
    )
    public_base_url: str = "http://localhost:8000"
    # Dashboard origin that hosts the shared Google (Supabase) login. The ChatGPT
    # OAuth flow hands users here so GPT, MCP, and dashboard share one identity.
    dashboard_url: str = "https://www.zynd.ai"
    # Persona's hosted login + onboarding (front-door). The ChatGPT/MCP OAuth flow
    # redirects users here to sign in and set up their persona; persona then calls
    # /oauth/complete with the verified session and bounces the browser back.
    persona_login_url: str = "https://persona.zynd.ai"
    # Legacy: cards once hosted the OAuth front door for MCP/ChatGPT connectors.
    # Unused now — every authorize flow (connector + ChatGPT Action) uses the
    # self-hosted page at {PUBLIC_BASE_URL}/oauth/login. Kept for env-file
    # compatibility with older deployments.
    cards_login_url: str = "https://cards.zynd.ai/auth"

    # Supabase (for Google sign-in via the dashboard). Used to verify a user's
    # Supabase access token server-side before issuing a ZYND token.
    supabase_url: str = ""
    supabase_anon_key: str = ""
    # Supabase project(s) whose tokens memory trusts, "url|anon_key" pairs
    # comma-separated. Empty (default) falls back to supabase_url/supabase_anon_key
    # alone — single-project behavior unchanged. During the aafo migration this
    # holds both xmfj and aafo so cards-web/persona-web sessions from either work.
    # The FIRST project also powers the self-hosted connector auth page
    # (/oauth/login): it must have Google + LinkedIn OIDC enabled and
    # {PUBLIC_BASE_URL}/oauth/login/callback registered as a redirect URL.
    trusted_supabase_projects: str = ""
    # Persona network integration (agent-persona backend). service_key authenticates
    # service-to-service calls + Supabase PostgREST reads of dm_threads (D3).
    persona_base_url: str = "https://persona.zynd.ai"
    supabase_service_key: str = ""
    # Gate for the persona cutover. OFF until Supabase is switched to the persona
    # project + verified — keeps persona resolution dormant in normal deploys.
    persona_enabled: bool = False
    # Browser origins allowed to call the API (dashboard + persona front-door, which
    # POSTs the session to /oauth/complete from the browser) — comma-separated.
    cors_origins: str = (
        "https://zynd.ai,https://www.zynd.ai,https://persona.zynd.ai,https://dev.persona.zynd.ai,"
        "https://cards.zynd.ai,https://dev.cards.zynd.ai,http://localhost:3000,http://localhost:3002"
    )

    @property
    def freshness_v2(self) -> bool:
        """Freshness v2 is effective only when every writer records evidence the same way,
        i.e. when the unified write path is also on. Legacy writers do not maintain
        base_confidence / last_seen_at / mention_count, so v2 on their own would decay
        facts from stale bases."""
        return self.feature_freshness_v2 and self.feature_fact_families

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def plugin_review_email_set(self) -> frozenset[str]:
        return frozenset(e.strip().lower() for e in self.plugin_review_emails.split(",") if e.strip())

    @property
    def trusted_supabase_project_list(self) -> list[tuple[str, str]]:
        if not self.trusted_supabase_projects:
            return [(self.supabase_url, self.supabase_anon_key)] if self.supabase_url else []
        pairs: list[tuple[str, str]] = []
        for entry in self.trusted_supabase_projects.split(","):
            entry = entry.strip()
            if "|" in entry:
                url, key = entry.split("|", 1)
                pairs.append((url.strip(), key.strip()))
        return pairs

    # M5 matching gates (brief §6.1).
    match_min_assertions: int = 5   # data-quality floor: skip thin profiles
    match_default_limit: int = 10

    # ── OAuth provider credentials (for MCP tools: Twitter, LinkedIn, Google, Notion) ──
    twitter_client_id: str = ""
    twitter_client_secret: str = ""
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    notion_client_id: str = ""
    notion_client_secret: str = ""

    # ── Exa / Tavily / Firecrawl (LinkedIn people search + profile enrichment) ──
    exa_api_key: str = ""
    tavily_api_key: str = ""
    firecrawl_api_key: str = ""

    # QuickEnrich contact-finder used by find_people. Empty disables that source.
    quickenrich_base_url: str = ""
    quickenrich_api_key: str = ""
    quickenrich_auth_header: str = "Authorization"
    quickenrich_timeout: float = 12.0

    # ── Zynd Network ──
    zynd_registry_url: str = "https://zns01.zynd.ai"
    zynd_deployer_url: str = "https://deployer.zynd.ai"
    zynd_developer_keypair_path: str = ""

    # ── Public page base URL (for published pages from the agent) ──
    public_page_base_url: str = ""

    @property
    def allowed_redirect_prefixes(self) -> list[str]:
        raw = f"{self.oauth_allowed_redirect_prefixes},{self.deployer_allowed_redirect_prefixes}"
        return [p.strip() for p in raw.split(",") if p.strip()]

    @property
    def mcp_origin(self) -> str:
        """Origin of the MCP server. MCP_PUBLIC_BASE_URL is often
        https://api.zynd.ai/mcp; FastMCP appends its own transport path, so a
        base that already ends in /mcp must be stripped to its origin."""
        parts = urlsplit(self.mcp_public_base_url)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def mcp_resource_url(self) -> str:
        """Canonical RFC 8707 resource indicator for the hosted MCP server —
        the URL Claude/ChatGPT register and the audience connector tokens are
        bound to."""
        return f"{self.mcp_origin}/mcp"

    @property
    def plugin_mcp_origin(self) -> str:
        parts = urlsplit(self.plugin_mcp_public_base_url)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def plugin_resource_url(self) -> str:
        path = urlsplit(self.plugin_mcp_public_base_url).path.rstrip("/")
        return f"{self.plugin_mcp_origin}{path}/mcp"

    @property
    def claude_plugin_mcp_origin(self) -> str:
        parts = urlsplit(self.claude_plugin_mcp_public_base_url)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def claude_plugin_resource_url(self) -> str:
        path = urlsplit(self.claude_plugin_mcp_public_base_url).path.rstrip("/")
        return f"{self.claude_plugin_mcp_origin}{path}/mcp"

    @model_validator(mode="after")
    def _refuse_default_secrets_in_production(self) -> "Settings":
        """Fail closed in production: never boot with an empty/known/short JWT
        secret, and never boot with a hardcoded confidential-client secret."""
        if self.environment != "production":
            return self
        problems: list[str] = []
        if not self.jwt_secret or self.jwt_secret == _DEV_JWT_SECRET or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET must be a strong random value (>=32 chars)")
        if not self.oauth_client_secret or self.oauth_client_secret == "zynd-oauth-secret":
            problems.append("OAUTH_CLIENT_SECRET must be overridden")
        if (
            not self.deployer_oauth_client_secret
            or self.deployer_oauth_client_secret == "change-me-deployer-oauth-secret"
        ):
            problems.append("DEPLOYER_OAUTH_CLIENT_SECRET must be overridden")
        if problems:
            raise ValueError("refusing to boot in production: " + "; ".join(problems))
        return self


settings = Settings()
