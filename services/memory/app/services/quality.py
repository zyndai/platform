"""S05 inbox quality — canonicalize, score, and triage MCP-reported facts.

Pure helpers (no DB) return group ∈ {right, look, noise}, a suggested public
predicate, and a human "Shows as" label. Callers decide whether to hard-drop.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Literal

from app.config import settings

logger = logging.getLogger(__name__)

Group = Literal["right", "look", "noise"]

# Default public remap when approving coding-agent predicates (mirrors findability).
_APPROVE_AS: dict[str, str] = {
    "has_skill": "has_expertise_in",
    "is_creating": "is_building",
    "intends_to": "is_building",
    "is_responsible_for": "is_building",
}

_PUBLIC_LABELS: dict[str, str] = {
    "is_founder_of": "Founded",
    "has_experience_in": "Experience",
    "is_building": "Currently building",
    "is_working_on": "Working on",
    "is_creating": "Creating",
    "intends_to": "Planning",
    "is_learning": "Learning",
    "is_seeking": "Seeking",
    "open_to": "Open to",
    "has_expertise_in": "Expert in",
    "has_skill": "Skilled in",
    "uses_tool": "Uses",
    "is_affiliated_with": "Works at",
    "is_located_in": "Based in",
    "is_responsible_for": "Responsible for",
}

_GENERIC_TOKENS = frozenset({
    "ai", "ml", "app", "apps", "tool", "tools", "code", "project", "projects",
    "work", "stuff", "thing", "things", "test", "tmp", "temp", "misc", "other",
    "none", "null", "undefined", "unknown", "n/a", "na", "todo", "wip",
})

# Placeholders are invalid facts, regardless of whether soft inbox triage is enabled.
PLACEHOLDER_TOKENS = frozenset({"general", "misc", "miscellaneous", "other", "none", "null", "undefined", "unknown", "n/a"})
TOPIC_PREDICATES = frozenset({"has_skill", "has_expertise_in", "is_learning", "uses_tool"})


def is_atomic_topic(value: str) -> bool:
    text = canonicalize(value)
    return bool(text and text.casefold() not in PLACEHOLDER_TOKENS
                and len(text) <= 100 and len(text.split()) <= 8
                and not re.search(r"[!?;\n]|\.\s|https?://|\b(?:founder of|founded|organized|worked at)\b", text, re.I))


def historical_learning(value: str) -> tuple[str, str] | None:
    """Correct only explicit historical statements, never infer a role from a topic."""
    text = canonicalize(value)
    founder = re.match(r"^(?:co[- ]?founder\s+(?:of|at)|founder\s+(?:of|at)|founded|co[- ]?founded)\s+(.+)$", text, re.I)
    if founder:
        return "is_founder_of", founder.group(1).split(",", 1)[0].strip()
    if re.match(r"^(?:organized|organised|previously worked|worked at|formerly)\b", text, re.I):
        return "has_experience_in", text
    return None

_INTERNAL_JARGON = frozenset({
    "worker trees", "worktree", "worktrees", "agent manager", "session goal",
    "task child", "subagent", "background process", "board_read", "board_post",
})

_KNOWN_TOOLS = frozenset({
    "claude", "claude code", "claude in chrome", "codex", "opencode",
    "cursor", "vscode", "vs code", "windsurf", "cline",
    "composio", "copilot", "github copilot", "chatgpt", "openai", "gemini",
    "docker", "kubernetes", "k8s", "npm", "pnpm", "yarn", "pip", "uv",
    "pytest", "jest", "playwright", "selenium", "terraform", "ansible",
    "aws", "gcp", "azure", "vercel", "netlify", "supabase", "firebase",
    "postgres", "postgresql", "redis", "mongodb", "mysql", "sqlite",
    "react", "next.js", "nextjs", "vue", "angular", "svelte", "fastapi",
    "django", "flask", "express", "nestjs", "rails", "spring",
})

_REPO_RE = re.compile(
    r"(?:"
    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"  # owner/repo
    r"|[A-Za-z]:\\|"  # windows path
    r"/(?:Users|home|var|tmp|opt)/"  # unix path root
    r"|\.git\b"
    r"|node_modules"
    r")",
    re.IGNORECASE,
)
_PATH_RE = re.compile(r"(?:^|[\s])(?:\.{0,2}/[\w./-]+|~\/[\w./-]+)")
_WHITESPACE_RE = re.compile(r"\s+")

# Soft daily cap for cards_mcp typed writes per user (enforced by caller).
DEFAULT_DAILY_CAP = 40


@dataclass(frozen=True)
class QualityResult:
    value: str
    group: Group
    suggested_predicate: str
    public_label: str
    drop: bool
    reason: str = ""


def canonicalize(value: str) -> str:
    """Trim, collapse whitespace, strip wrapping quotes/punctuation noise."""
    text = (value or "").strip().strip("\"'`")
    text = _WHITESPACE_RE.sub(" ", text)
    return text


def public_predicate_for(predicate: str) -> str:
    return _APPROVE_AS.get(predicate, predicate)


def public_label_for(predicate: str, object_name: str) -> str:
    """Human 'Shows as' string for the review queue / card."""
    obj = canonicalize(object_name)
    public_pred = public_predicate_for(predicate)
    if public_pred == "is_building":
        return obj
    prefix = _PUBLIC_LABELS.get(public_pred) or _PUBLIC_LABELS.get(predicate)
    if prefix:
        return f"{prefix}: {obj}"
    return obj


def surface_dedupe_key(predicate: str, object_name: str) -> str:
    """Collapse same name + public-predicate family on card/review surfaces."""
    family = public_predicate_for(predicate)
    return f"{family}|{canonicalize(object_name).lower()}"


def assess(
    value: str,
    *,
    intended_predicate: str,
    field: str = "",
) -> QualityResult:
    """Score one candidate. field is the MCP report_user_info field name."""
    raw = value or ""
    cleaned = canonicalize(raw)
    suggested = intended_predicate
    if not cleaned:
        return QualityResult(
            value="", group="noise", suggested_predicate=suggested,
            public_label="", drop=True, reason="empty",
        )

    lower = cleaned.lower()
    historical = historical_learning(cleaned) if intended_predicate == "is_learning" else None
    reason = ""
    group: Group = "right"

    if lower in PLACEHOLDER_TOKENS:
        group, reason = "noise", "placeholder"
    elif historical:
        suggested = historical[0]
        group, reason = "look", "historical_role"
    elif intended_predicate in TOPIC_PREDICATES and not is_atomic_topic(cleaned):
        group, reason = "noise", "narrative_topic"
    elif len(cleaned) < 2 or lower in _GENERIC_TOKENS:
        group, reason = "noise", "short_or_generic"
    elif _REPO_RE.search(cleaned) or _PATH_RE.search(cleaned):
        group, reason = "noise", "repo_or_path"
    elif lower in _INTERNAL_JARGON or any(j in lower for j in _INTERNAL_JARGON):
        group, reason = "noise", "internal_jargon"
    elif field == "projects" and lower in _KNOWN_TOOLS:
        group, reason = "look", "tool_as_project"
        suggested = "uses_tool"
    elif field == "goals" and (
        lower in _KNOWN_TOOLS or _REPO_RE.search(cleaned) or len(cleaned.split()) <= 2
    ):
        # Short goal strings often are product names or tools — ask for a look.
        group, reason = "look", "ambiguous_goal"
        if lower in _KNOWN_TOOLS:
            suggested = "uses_tool"
    elif field in ("tools", "languages", "frameworks", "skills") and len(cleaned) > 80:
        group, reason = "look", "overlong_skill"
    elif any(ch in cleaned for ch in ("{", "}", "=", ";")) and field != "notes":
        group, reason = "noise", "code_shaped"

    # Hard-drop only empty / clearly junk; keep noise visible in the queue.
    drop = reason in ("empty", "placeholder", "narrative_topic") or (group == "noise" and reason == "code_shaped" and len(cleaned) < 4)

    label = public_label_for(suggested, historical[1] if historical else cleaned)
    return QualityResult(
        value=cleaned,
        group=group,
        suggested_predicate=suggested,
        public_label=label,
        drop=drop,
        reason=reason,
    )


def assess_typed_field(
    field: str,
    values: list[str] | None,
    *,
    predicate: str,
) -> list[QualityResult]:
    """Assess a list of typed MCP values; skips empties after canonicalize."""
    out: list[QualityResult] = []
    seen: set[str] = set()
    for raw in values or []:
        result = assess(raw, intended_predicate=predicate, field=field)
        if not result.value:
            continue
        key = result.value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(result)
    return out


def log_observe(user_id: str, field: str, result: QualityResult) -> None:
    """Observe-mode log — what the filter would do without enforcing."""
    logger.info(
        "s05_quality observe user=%s field=%s value=%r group=%s drop=%s reason=%s suggested=%s",
        user_id, field, result.value, result.group, result.drop, result.reason,
        result.suggested_predicate,
    )


def dedupe_suggestion_rows(rows: list[dict]) -> list[dict]:
    """Keep first row per (public-predicate family, canonical object)."""
    seen: set[str] = set()
    out: list[dict] = []
    for row in rows:
        key = surface_dedupe_key(row.get("predicate", ""), row.get("object", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


# ── Second sighting ───────────────────────────────────────────────────────────────

SECOND_SIGHTING_MAX_CONFIDENCE = 0.9


def visible_sql(alias: str = "a") -> str:
    """SQL condition that is false for an inferred skill or tool seen only once.

    One passing mention ("working in some-repo's webpack config") must not put a skill into
    context or the review inbox; seeing it in a second chunk, or the person declaring it,
    does. Declared facts and anything strongly evidenced are visible at once. `version`
    counts observations until Phase 4's mention_count exists. TRUE when the rule is off.
    """
    if not settings.feature_strict_tech:
        return "TRUE"
    mentions = f"{alias}.mention_count" if settings.freshness_v2 else f"{alias}.version"
    return (
        f"NOT ({alias}.predicate IN ('has_skill', 'uses_tool') AND {alias}.source = 'inferred' "
        f"AND {alias}.confidence < {SECOND_SIGHTING_MAX_CONFIDENCE} AND {mentions} < 2)"
    )
