"""
Shared keyword cache + one post per section per handle/day.

Run: python -m pytest tests/test_suggested_posts.py -v
"""
from models.card import AgentProfileCard, WritingSample
from services import suggested_posts as sp


def _card(**kwargs) -> AgentProfileCard:
    defaults = dict(
        id="testid",
        status="published",
        handle="jane",
        working_on=["Building with AI"],
        can_help_with=["Code review"],
        connect_with=["Founders"],
        love_talking_about=["Open source"],
    )
    defaults.update(kwargs)
    return AgentProfileCard(**defaults)


def _post(url, platform="x", excerpt="talking about AI today"):
    return {
        "url": url,
        "platform": platform,
        "excerpt": excerpt,
        "author": "someone",
        "posted_at": "2026-09-24",
    }


def _pool_for(queries):
    pool = {}
    for i, (field, query) in enumerate(queries):
        if not query:
            continue
        pool[field] = [
            _post(f"https://x.com/{field}/{n}", excerpt=query) for n in range(8)
        ]
    return pool


def test_intent_queries_uses_canonical_and_keeps_empty_slots():
    card = _card(
        working_on=["building with ai", "Side project"],
        can_help_with=[],
        connect_with=["  Founders  "],
    )
    assert sp.intent_queries(card) == [
        ("working_on", "Building with AI"),
        ("can_help_with", ""),
        ("connect_with", "Founders"),
        ("love_talking_about", "Open source"),
    ]


def test_unknown_phrase_still_used():
    card = _card(working_on=["AI infra"])
    assert sp.intent_queries(card)[0] == ("working_on", "AI infra")


def test_same_handle_same_day_same_picks():
    q = sp.intent_queries(_card())
    pool = _pool_for(q)
    a, _, _ = sp.pick_day("jane", "2026-09-24", q, pool, [])
    b, _, _ = sp.pick_day("jane", "2026-09-24", q, pool, [])
    assert [p["url"] if p else None for p in a] == [p["url"] if p else None for p in b]


def test_different_handles_same_keywords_different_picks():
    q = sp.intent_queries(_card())
    pool = _pool_for(q)
    jane, _, _ = sp.pick_day("jane", "2026-09-24", q, pool, [])
    bob, _, _ = sp.pick_day("bob", "2026-09-24", q, pool, [])
    assert [p["url"] for p in jane if p] != [p["url"] for p in bob if p]


def test_empty_field_is_null_slot():
    q = sp.intent_queries(_card(can_help_with=[]))
    posts, _, _ = sp.pick_day("jane", "2026-09-24", q, _pool_for(q), [])
    assert posts[1] is None
    assert posts[0]["field"] == "working_on"


def test_two_users_same_keyword_fetch_once():
    cache = {}
    calls = []

    def search_x(query):
        calls.append(query)
        return [_post(f"https://x.com/{query}/{i}", excerpt=query) for i in range(8)]

    jane = _card(handle="jane")
    bob = _card(id="bobid", handle="bob")
    sp.refresh_snapshot("jane", jane, None, "2026-09-24", cache, search_x, [])
    sp.refresh_snapshot("bob", bob, None, "2026-09-24", cache, search_x, [])
    assert len(calls) == 4
    assert set(calls) == {"Building with AI", "Code review", "Founders", "Open source"}


def test_snapshot_hit_skips_keyword_lookup_fetch():
    card = _card()
    calls = {"n": 0}

    def search_x(query):
        calls["n"] += 1
        return []

    snap = {
        "date": "2026-09-24",
        "queries_hash": sp.queries_hash(sp.intent_queries(card)),
        "posts": [{"field": "working_on", "url": "https://x.com/cached"}],
        "shown_urls": ["https://x.com/cached"],
        "summary": "cached briefing",
    }
    out, wrote = sp.refresh_snapshot("jane", card, snap, "2026-09-24", {}, search_x, [])
    assert calls["n"] == 0
    assert wrote is None
    assert out["posts"][0]["url"] == "https://x.com/cached"


def test_same_day_reuses_keyword_cache_without_refetch():
    cache = {
        sp.keyword_key("Building with AI"): {
            "fetched_on": "2026-09-24",
            "posts": [_post(f"https://x.com/ai/{i}", excerpt="Building with AI") for i in range(8)],
        },
        sp.keyword_key("Code review"): {
            "fetched_on": "2026-09-24",
            "posts": [_post(f"https://x.com/cr/{i}", excerpt="Code review") for i in range(8)],
        },
        sp.keyword_key("Founders"): {
            "fetched_on": "2026-09-24",
            "posts": [_post(f"https://x.com/f/{i}", excerpt="Founders") for i in range(8)],
        },
        sp.keyword_key("Open source"): {
            "fetched_on": "2026-09-24",
            "posts": [_post(f"https://x.com/os/{i}", excerpt="Open source") for i in range(8)],
        },
    }
    calls = {"n": 0}

    def search_x(query):
        calls["n"] += 1
        return []

    _, wrote = sp.refresh_snapshot("jane", _card(), None, "2026-09-24", cache, search_x, [])
    assert calls["n"] == 0
    assert wrote is not None
    assert len([p for p in wrote["posts"] if p]) == 4


def test_new_day_refetches_stale_keywords_once():
    cache = {
        sp.keyword_key("Building with AI"): {
            "fetched_on": "2026-09-23",
            "posts": [_post("https://x.com/old/ai")],
        }
    }
    calls = []

    def search_x(query):
        calls.append(query)
        return [_post(f"https://x.com/new/{query}", excerpt=query)]

    card = _card(can_help_with=[], connect_with=[], love_talking_about=[])
    sp.refresh_snapshot("jane", card, None, "2026-09-24", cache, search_x, [])
    assert calls == ["Building with AI"]
    assert cache[sp.keyword_key("Building with AI")]["fetched_on"] == "2026-09-24"


def test_next_day_skips_shown_urls():
    posts = [_post(f"https://x.com/ai/{i}", excerpt="Building with AI") for i in range(8)]
    cache = {
        sp.keyword_key("Building with AI"): {
            "fetched_on": "2026-09-24",
            "posts": posts,
        }
    }

    def search_x(query):
        return posts

    card = _card(can_help_with=[], connect_with=[], love_talking_about=[])
    d1, wrote1 = sp.refresh_snapshot("jane", card, None, "2026-09-24", cache, search_x, [])
    d2, wrote2 = sp.refresh_snapshot(
        "jane",
        card,
        wrote1,
        "2026-09-25",
        cache,
        search_x,
        [],
    )
    assert wrote2["posts"][0]["url"] != wrote1["posts"][0]["url"]
    assert wrote1["posts"][0]["url"] in wrote2["shown_urls"]


def test_owner_writing_samples_excluded_from_linkedin_pool():
    owner = _card(
        writing_samples=[
            WritingSample(platform="linkedin", excerpt="my own post about Building with AI", url="https://linkedin.com/feed/mine")
        ]
    )
    others = [
        WritingSample(platform="linkedin", excerpt="Building with AI at a startup", url="https://linkedin.com/feed/other"),
        WritingSample(platform="x", excerpt="Building with AI tweet", url="https://x.com/other/1"),
    ]
    pool = sp.linkedin_candidates("Building with AI", others, exclude_urls={s.url for s in owner.writing_samples})
    urls = [p["url"] for p in pool]
    assert "https://linkedin.com/feed/mine" not in urls
    assert "https://linkedin.com/feed/other" in urls
    assert "https://x.com/other/1" not in urls


def test_empty_fields_summary_is_null():
    card = _card(working_on=[], can_help_with=[], connect_with=[], love_talking_about=[])
    calls = []
    _, wrote = sp.refresh_snapshot(
        "jane", card, None, "2026-09-24", {}, lambda q: [], [], llm=lambda k, p: calls.append(k) or "x"
    )
    assert calls == []
    assert wrote["summary"] is None


def test_summary_is_topic_briefing_from_keyword_posts():
    cache = {
        sp.keyword_key("Building with AI"): {
            "fetched_on": "2026-09-24",
            "posts": [_post("https://x.com/ai/1", excerpt="GPT-5 shipped to API")],
        }
    }
    card = _card(can_help_with=[], connect_with=[], love_talking_about=[])
    _, wrote = sp.refresh_snapshot(
        "jane",
        card,
        None,
        "2026-09-24",
        cache,
        lambda q: [],
        [],
        llm=lambda keyword, posts: f"brief:{keyword}:{posts[0]['excerpt']}",
    )
    assert wrote["summary"] == "Building with AI: brief:Building with AI:GPT-5 shipped to API"


def test_two_users_same_keyword_summarize_once():
    cache = {}
    llm_calls = []

    def search_x(query):
        return [_post(f"https://x.com/{query}/1", excerpt=query)]

    def llm(keyword, posts):
        llm_calls.append(keyword)
        return f"news about {keyword}"

    jane = _card(can_help_with=[], connect_with=[], love_talking_about=[])
    bob = _card(id="bobid", handle="bob", can_help_with=[], connect_with=[], love_talking_about=[])
    sp.refresh_snapshot("jane", jane, None, "2026-09-24", cache, search_x, [], llm=llm)
    sp.refresh_snapshot("bob", bob, None, "2026-09-24", cache, search_x, [], llm=llm)
    assert llm_calls == ["Building with AI"]


def test_snapshot_hit_without_summary_backfills_from_keyword_cache():
    card = _card(can_help_with=[], connect_with=[], love_talking_about=[])
    cache = {
        sp.keyword_key("Building with AI"): {
            "fetched_on": "2026-09-24",
            "posts": [_post("https://x.com/ai/1", excerpt="GPT-5 shipped")],
            "summary": "",
        }
    }
    snap = {
        "date": "2026-09-24",
        "queries_hash": sp.queries_hash(sp.intent_queries(card)),
        "posts": [{"field": "working_on", "url": "https://x.com/ai/1"}],
        "shown_urls": ["https://x.com/ai/1"],
        "summary": None,
    }
    calls = []
    out, wrote = sp.refresh_snapshot(
        "jane",
        card,
        snap,
        "2026-09-24",
        cache,
        lambda q: calls.append("search") or [],
        [],
        llm=lambda k, p: f"brief:{k}",
    )
    assert "search" not in calls
    assert wrote is not None
    assert wrote["posts"] == snap["posts"]
    assert wrote["summary"] == "Building with AI: brief:Building with AI"


def test_snapshot_hit_keeps_stored_summary_without_llm():
    card = _card()
    calls = []
    snap = {
        "date": "2026-09-24",
        "queries_hash": sp.queries_hash(sp.intent_queries(card)),
        "posts": [{"field": "working_on", "url": "https://x.com/cached"}],
        "shown_urls": ["https://x.com/cached"],
        "summary": "cached briefing",
    }
    out, wrote = sp.refresh_snapshot(
        "jane", card, snap, "2026-09-24", {}, lambda q: [], [], llm=lambda k, p: calls.append(k)
    )
    assert wrote is None
    assert calls == []
    assert out["summary"] == "cached briefing"
