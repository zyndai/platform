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


def classify(user_agent: str | None) -> str:
    """Return actor_class ∈ {human, ai_agent, search_bot, unknown}."""
    ua = user_agent or ""
    if not ua.strip():
        return "unknown"
    for token in _AI_AGENT:
        if token in ua:
            return "ai_agent"
    for token in _SEARCH_BOT:
        if token in ua:
            return "search_bot"
    if "Mozilla/" in ua:
        return "human"
    return "unknown"
