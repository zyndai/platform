"""User-Agent → actor_class for S04 card_events."""

_AI_AGENT = (
    "GPTBot",
    "ChatGPT-User",
    "OAI-SearchBot",
    "ClaudeBot",
    "Claude-User",
    "anthropic-ai",
    "PerplexityBot",
    "Google-Extended",
    "Bytespider",
    "CCBot",
    "Amazonbot",
    "Applebot-Extended",
    "Meta-ExternalAgent",
    "cohere-ai",
)

_SEARCH_BOT = (
    "Googlebot",
    "Bingbot",
    "DuckDuckBot",
    "Slurp",
    "Baiduspider",
    "YandexBot",
)

# Store only these fixed labels, never the raw (potentially identifying) header.
AGENT_PROVIDERS = {
    "GPTBot": "ChatGPT / OpenAI", "ChatGPT-User": "ChatGPT / OpenAI",
    "OAI-SearchBot": "ChatGPT / OpenAI", "ClaudeBot": "Claude",
    "Claude-User": "Claude", "anthropic-ai": "Claude",
    "PerplexityBot": "Perplexity", "Google-Extended": "Google",
    "Bytespider": "ByteDance", "CCBot": "Common Crawl",
    "Amazonbot": "Amazon", "Applebot-Extended": "Apple",
    "Meta-ExternalAgent": "Meta", "cohere-ai": "Cohere",
}


def agent_name(user_agent: str | None) -> str | None:
    ua = (user_agent or "").lower()
    return next((token for token in _AI_AGENT if token.lower() in ua), None)


def classify(user_agent: str | None) -> str:
    """Return actor_class ∈ {human, ai_agent, search_bot, unknown}."""
    ua = user_agent or ""
    if not ua.strip():
        return "unknown"
    if agent_name(ua):
        return "ai_agent"
    for token in _SEARCH_BOT:
        if token in ua:
            return "search_bot"
    if "Mozilla/" in ua:
        return "human"
    return "unknown"
