"""Social copy from selected recap evidence using the existing OpenRouter client."""
import json
import logging
import re

import config

logger = logging.getLogger(__name__)
CAPTION_TIMEOUT_SECONDS = 15
MAX_CAPTION_WORDS = 130
MAX_CAPTION_CHARACTERS = 1800


def _numbers(text):
    return {number.replace(",", "") for number in re.findall(r"\d+(?:[.,]\d+)*", text)}


def generate_social_caption(snapshot: dict, fallback: str) -> dict:
    facts = [{key: h[key] for key in ("id", "kind", "title", "count") if key in h}
             for h in snapshot["highlights"] if h["kind"] in ("repository", "github", "shipped", "learned")]
    if not facts or not config.OPENROUTER_API_KEY:
        return {"caption": fallback, "source": "template"}
    period = snapshot["label"] + (" so far" if snapshot["in_progress"] else "")
    # Keep the achievement sentence verbatim. The LLM writes the social framing,
    # so repository creation cannot turn into shipping or invented learning.
    prefix = f"Hi connections, in {period}, "
    suffix = " Looking forward to sharing what comes next."
    if not fallback.startswith(prefix) or not fallback.endswith(suffix):
        return {"caption": fallback, "source": "template"}
    factual_sentence = fallback[len(prefix):-len(suffix)]
    evidence = {"period": snapshot["label"], "in_progress": snapshot["in_progress"]}
    try:
        response = config.get_llm_client().with_options(timeout=CAPTION_TIMEOUT_SECONDS, max_retries=0).chat.completions.create(
            model=config.OPENROUTER_MODEL, temperature=0.4, max_tokens=600,
            response_format={"type": "json_object"}, messages=[
                {"role": "system", "content": (
                    'Write the opening and closing for a friendly first-person LinkedIn progress recap. '
                    'Return JSON only: {"opening":"...","closing":"..."}. '
                    'The application inserts an exact, verified achievement sentence between them. '
                    'Do not write, infer, or repeat any achievements yourself. '
                    'Opening: 10–25 words, start exactly with "Hi connections,", mention the supplied period '
                    'exactly, and introduce a personal builder update naturally. For in_progress include '
                    '"so far". Closing: 8–20 words, a casual invitation to connect or discuss similar work. '
                    'Keep it warm and human, without hype, formal corporate phrases, hashtags, links, '
                    'bullet points, numbers beyond the period, claimed outcomes, or project names. '
                    'Do not claim anything was shipped, learned, created or mastered; facts are inserted separately.'
                )},
                {"role": "user", "content": json.dumps(evidence)},
            ])
        data = json.loads(response.choices[0].message.content or "{}")
        opening, closing = data.get("opening"), data.get("closing")
        if not isinstance(opening, str) or not isinstance(closing, str):
            raise ValueError("Invalid caption response")
        opening, closing = " ".join(opening.split()), " ".join(closing.split())
        framing = opening + " " + closing
        if (not opening.startswith("Hi connections,") or evidence["period"] not in opening
                or not 12 <= len(framing.split()) <= 70
                or not _numbers(framing) <= _numbers(evidence["period"])
                or re.search(r"https?://|www\.|\S+@\S+|#", framing)
                or re.search(r"\b(?:created|shipped|launched|learned|learning milestones|mastered|achieved|contributions|repositories|revenue|customers)\b", framing, re.I)
                or (snapshot["in_progress"] and "so far" not in opening.lower())):
            raise ValueError("Caption framing contains unsupported claims")
        caption = f"{opening} {factual_sentence} {closing}"
        if len(caption) > MAX_CAPTION_CHARACTERS or len(caption.split()) > MAX_CAPTION_WORDS:
            raise ValueError("Caption too long")
        return {"caption": caption, "source": "llm"}
    except Exception:
        # Never log the model's copy or the owner's evidence.
        logger.warning("Recap caption generation unavailable; using factual caption")
        return {"caption": fallback, "source": "template"}
