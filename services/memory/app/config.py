from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime config, loaded from environment / .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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

    # M2 — JWT + OAuth (dev-grade; see docs/CHATGPT_PLUGIN.md security notes).
    jwt_secret: str = "dev-jwt-secret-change-me-in-production-0123456789"
    jwt_issuer: str = "zynd"
    access_token_ttl_seconds: int = 3600
    refresh_token_ttl_seconds: int = 30 * 24 * 3600
    mcp_token_ttl_seconds: int = 90 * 24 * 3600   # long-lived token pasted into MCP clients
    oauth_client_id: str = "zynd-chatgpt"
    oauth_client_secret: str = "zynd-oauth-secret"
    # Comma-separated allowlist of redirect_uri prefixes (prevents open redirect).
    oauth_allowed_redirect_prefixes: str = (
        "https://chat.openai.com/aip/,https://chatgpt.com/aip/,http://localhost"
    )
    public_base_url: str = "http://localhost:8000"
    # Dashboard origin that hosts the shared Google (Supabase) login. The ChatGPT
    # OAuth flow hands users here so GPT, MCP, and dashboard share one identity.
    dashboard_url: str = "https://www.zynd.ai"
    # Persona's hosted login + onboarding (front-door). The ChatGPT/MCP OAuth flow
    # redirects users here to sign in and set up their persona; persona then calls
    # /oauth/complete with the verified session and bounces the browser back.
    persona_login_url: str = "https://persona.zynd.ai"

    # Supabase (for Google sign-in via the dashboard). Used to verify a user's
    # Supabase access token server-side before issuing a ZYND token.
    supabase_url: str = ""
    supabase_anon_key: str = ""
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
        "https://zynd.ai,https://www.zynd.ai,https://persona.zynd.ai,http://localhost:3000"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # M5 matching gates (brief §6.1).
    match_min_assertions: int = 5   # data-quality floor: skip thin profiles
    match_default_limit: int = 10

    @property
    def allowed_redirect_prefixes(self) -> list[str]:
        return [p.strip() for p in self.oauth_allowed_redirect_prefixes.split(",") if p.strip()]


settings = Settings()
