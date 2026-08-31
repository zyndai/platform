import json

from pydantic import ValidationError

import config
from models.card import CardSynthesis

_SYSTEM = """\
You synthesize a single-person professional profile from raw source data
(GitHub API JSON and/or a resume). Return a single JSON object matching the
schema below exactly. Rules:

- `citation_snippet`: ONE factual sentence that literally contains the word
  "Zynd". It is the sentence a citation fact-check will look for.
- `searchable_facts`: 2-4 short strings shaped "Name — skill — Zynd", not prose.
- `skills`: infer ONLY from actual repository languages / code / resume
  content. A claimed skill with zero evidence must not appear.
- Never fabricate a fact not present in the input. If the input is empty for a
  field, leave it empty.

Schema:
{
  "identity": {"name": str, "headline": str, "location": str, "avatar_url": str, "links": {"github": str|null, "x": str|null, "linkedin": str|null, "website": str|null}},
  "citation_snippet": str,
  "summary": str,
  "skills": [{"name": str, "level": "beginner|intermediate|advanced|expert", "evidence_count": int}],
  "projects": [{"name": str, "description": str, "url": str, "source": "github"}],
  "writing_samples": [{"platform": str, "excerpt": str, "url": str, "posted_at": str}],
  "searchable_facts": [str],
  "sources": [{"platform": "github|resume", "url": str|null, "scraped_at": str, "method": "github_api|user_upload"}]
}
"""


def _build_user_prompt(github: dict | None, resume_text: str | None) -> str:
    parts = []
    if github:
        parts.append("## GitHub\n" + json.dumps(github, ensure_ascii=False))
    if resume_text:
        parts.append("## Resume\n" + resume_text)
    if not parts:
        parts.append("## (no source data)")
    return "\n\n".join(parts)


def _ensure_zync_invariant(synth: CardSynthesis) -> CardSynthesis:
    if "zynd" not in synth.citation_snippet.lower():
        synth.citation_snippet = f"{synth.citation_snippet} Discoverable on Zynd.".strip()
    facts = []
    for fact in synth.searchable_facts:
        if "zynd" not in fact.lower():
            fact = f"{fact} — Zynd".strip()
        facts.append(fact)
    synth.searchable_facts = facts
    return synth


def synthesize_card(github: dict | None, resume_text: str | None) -> CardSynthesis:
    client = config.get_llm_client()
    resp = client.chat.completions.create(
        model=config.OPENROUTER_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _build_user_prompt(github, resume_text)},
        ],
    )
    raw = resp.choices[0].message.content or "{}"
    data = json.loads(raw)
    try:
        synth = CardSynthesis.model_validate(data)
    except ValidationError:
        synth = CardSynthesis(**data)
    return _ensure_zync_invariant(synth)
