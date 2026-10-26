"""One re-rank for every source (people search plan, Phase 1.2-1.5)."""
import pytest

from app.services import people_results as pr
from app.services.people_query import parse_target_heuristic

QUERY = parse_target_heuristic("seed investor who backs developer tools in Pune")


def external(name, headline, location, index=0):
    title, _, company = headline.partition(" at ")
    return pr.person_from_external({"name": name, "title": title, "company": company, "location": location,
                                    "linkedin_url": f"https://linkedin.com/in/{name.lower()}"}, index)


def test_features_read_role_topics_and_place_the_same_for_any_source():
    f = pr.features(external("Asha", "Investor at Developer Tools Fund", "Pune, India"), QUERY)
    assert f["role_fit"] == 1.0 and f["location_fit"] == 1.0
    f = pr.features(external("Tom", "Product Manager at Acme", "Paris"), QUERY)
    assert f["role_fit"] == 0.0 and f["location_fit"] == 0.0


def test_a_linkedin_person_who_fits_beats_a_weak_card_and_one_who_does_not_fit_cannot():
    fits = external("Asha", "Investor at Developer Tools Fund", "Pune, India")
    misses = external("Tom", "Product Manager at Acme", "Paris")
    weak_card = pr.person_from_card({"handle": "w", "name": "W", "match_score": 0.3, "claimed": True})
    ranked = pr.merge_people(pr.rescore([fits, misses, weak_card], QUERY))
    names = [p["name"] for p in ranked]
    assert names.index("Asha") < names.index("W") and names[-1] == "Tom" or names.index("Tom") > names.index("Asha")
    assert fits["score"] > misses["score"] * 1.5


def test_found_by_two_sources_is_the_better_score_plus_a_little():
    card = pr.person_from_card({"handle": "ada", "name": "Ada", "match_score": 0.6, "claimed": True})
    zynd = pr.person_from_zynd({"similarity": 0.4}, {"handle": "ada", "name": "Ada", "claimed": True}, "u")
    (one,) = pr.merge_people([card, zynd])
    assert one["score"] == 0.65


def test_strong_means_the_asked_role_and_a_topic_or_place():
    a = external("Asha", "Investor at Developer Tools Fund", "Pune")
    b = external("Tom", "Investor at Bank", "Paris")
    pr.rescore([a, b], QUERY)
    assert pr.is_strong(a) and not pr.is_strong(b)
    assert pr.strong_count([a, b]) == 1
    relaxed = pr.person_from_card({"handle": "r", "name": "R", "match_score": 0.9, "claimed": True, "relaxed": ["location"]})
    assert not pr.is_strong(relaxed)


def test_quality_labels_and_the_note_when_nothing_is_exact():
    a = external("Asha", "Investor at Developer Tools Fund", "Pune")
    b = external("Tom", "Investor at Bank", "Paris")
    pr.rescore([a, b], QUERY)
    # neither LinkedIn record can show the topic asked (developer tools): Asha in the right city is close,
    # Tom, also in the wrong city, is loose
    assert "closest" in pr.label_quality([a, b]) and (a["match_quality"], b["match_quality"]) == ("close", "loose")
    c = external("Cy", "Designer at Studio", "Paris")
    pr.rescore([c], QUERY)
    assert "closest" in pr.label_quality([c]) and c["match_quality"] == "loose" and "_features" not in c


def test_why_is_specific_ordered_and_at_most_three():
    card = pr.person_from_card({
        "handle": "a", "name": "A", "headline": "Seed investor", "location": "Pune, India", "claimed": True, "match_score": 0.8,
        "why": ["Matches your search terms", "Strong overall match for your query",
                "Approved fact: backs developer tools", "Based in Pune, India", "Wants to meet people like you: Founders"]})
    why = pr.specific_why(card, QUERY)
    assert why == ["Investor (headline)", "backs developer tools (approved fact)", "Pune, India"]
    relaxed = pr.person_from_card({"handle": "b", "name": "B", "headline": "Investor", "location": "Paris", "claimed": True,
                                   "match_score": 0.5, "why": ["Not in Pune (closest match)"]})
    assert "Not in Pune (closest match)" in pr.specific_why(relaxed, QUERY)
    assert pr.specific_why(external("Z", "Designer at X", "Paris"), QUERY) == ["Found on LinkedIn"]


def test_a_linkedin_title_is_judged_by_the_titles_the_request_used():
    """People search 3.1: a Venture Partner was retrieved as an investor and is one, though the
    headline never says "investor"; a grievance officer is not, whatever the headline says."""
    q = parse_target_heuristic("investor in India")
    venture = external("Priya", "Venture Partner at Seed Fund", "Pune, India")
    officer = external("Ivan", "Investor Grievance Officer at Dayco", "Mumbai, India")
    sales = external("Sam", "Sales Manager at Investor Relations Inc", "Pune, India")   # an excluded word in the title only
    assert pr.features(venture, q)["role_fit"] == 1.0
    assert pr.features(officer, q)["role_fit"] == 0.0
    assert pr.features(sales, q)["role_fit"] == 0.0
    # A company that merely contains an excluded word does not count against a real title.
    assert pr.features(external("Eve", "Investor at Support Capital", "Pune, India"), q)["role_fit"] == 1.0
    # A Card's role is still read from its headline: the title lists are for people found by title.
    card = pr.person_from_card({"handle": "c", "name": "C", "headline": "Venture Partner", "claimed": True})
    assert pr.features(card, q)["role_fit"] == 0.0


def test_the_reason_says_title_when_the_headline_does_not_name_the_role():
    q = parse_target_heuristic("investor in India")
    assert pr.specific_why(external("Priya", "Venture Partner at Seed Fund", "Pune, India"), q)[0] == "Investor (title)"
    assert pr.specific_why(external("Asha", "Investor at Fund", "Pune, India"), q)[0] == "Investor (headline)"


# ── what the live investor query showed (the corpus has no investors, so every answer is a closest match) ──

INVESTOR = parse_target_heuristic("seed-stage investor who backs AI dev tools in India")


def _live_card(handle, headline, raw_reasons):
    """A Cards hit as the pipeline shapes it: the raw reasons go through people_discovery._why first."""
    from app.services.people_discovery import _why
    return pr.person_from_card({"handle": handle, "name": handle, "headline": headline, "location": "India",
                                "claimed": True, "match_score": 0.55, "why": _why(raw_reasons)})


FACTS = [{"type": "memory", "text": "AI governance", "source": "declared", "age_days": 2},
         {"type": "memory", "text": "developing AI governance solutions", "source": "declared", "age_days": 2},
         {"type": "memory", "text": "India", "source": "declared", "age_days": 2}]


@pytest.mark.parametrize("loosened", ["Not an investor (closest match)", "Not a investor (closest match)"])   # Cards' new and old wording
def test_a_person_with_many_facts_still_says_what_was_loosened(loosened):
    """Cards lists the loosened-role reason last; a cut at four reasons dropped it for anyone with a few
    approved facts, so a non-investor looked like an answer and the note was the only hint."""
    person = _live_card("revanth", "Co-Founder at Evolune EdgeTech", [
        "Matches your search terms", *FACTS, "Role match", "Based in India", loosened])
    why = pr.specific_why(person, INVESTOR)
    assert loosened in why and len(why) <= 3
    assert "Role match" not in why                    # Cards' own word for the role found anywhere on the card


@pytest.mark.parametrize("loosened", ["Not an investor (closest match)", "Not a investor (closest match)"])
def test_the_loosening_reason_does_not_make_a_non_investor_look_like_one(loosened):
    """The reason names the role it could not find; reading it as evidence of the role gave a
    developer 'Investor (on their profile)' next to 'Not an investor'."""
    person = _live_card("atmegabuzz", "AI Systems Engineer | Backend & Protocol Developer", [
        "Matches your search terms", "Role match", "Based in Pune Division, Maharashtra, India", loosened])
    assert pr.features(person, INVESTOR)["role_fit"] == 0.0
    why = pr.specific_why(person, INVESTOR)
    assert not any(w.startswith("Investor") for w in why) and loosened in why


def test_a_real_investor_is_still_one_and_still_says_so():
    person = _live_card("ivy", "Seed investor in AI", ["Matches your search terms", "Based in India"])
    assert pr.features(person, INVESTOR)["role_fit"] == 1.0
    assert pr.specific_why(person, INVESTOR)[0] == "Investor (headline)"


def test_results_nothing_ranked_the_reasons_of_show_at_most_four():
    people = [pr.person_from_card({"handle": "a", "name": "A", "claimed": True,
                                   "why": [f"reason {i}" for i in range(8)]})]
    assert len(people[0]["why"]) == 8                  # kept whole while merging
    assert len(pr.cap_why(people)[0]["why"]) == pr.SHOWN_WHY == 4


# ── quality first, capped scores (people search quality plan, B) ─────────────────

INDIA = parse_target_heuristic("seed-stage investor who backs AI dev tools in India")


def relaxed_card(handle, score, headline="Software developer", location="Pune, India"):
    person = pr.person_from_card({"handle": handle, "name": handle.title(), "headline": headline, "location": location,
                                  "claimed": True, "match_score": score, "why": ["Not an investor (closest match)"]})
    person["relaxed"] = ["location", "role"]
    return person


def test_a_close_linkedin_investor_outranks_a_loose_card_that_scored_higher():
    li = pr.person_from_external({"name": "Gita", "title": "General Partner", "company": "Grayscale Ventures",
                                  "location": "Bengaluru, India", "linkedin_url": "https://linkedin.com/in/g", "score": 0.8}, 0)
    dev = relaxed_card("dev", 0.85)
    ordered = pr.order_by_quality(pr.rescore([dev, li], INDIA))
    assert [p["name"] for p in ordered] == ["Gita", "Dev"]
    # the LinkedIn investor meets the role and the place; the topic cannot be checked on LinkedIn: close
    assert (ordered[0]["match_quality"], ordered[1]["match_quality"]) == ("close", "loose")


def test_a_score_never_says_more_than_its_label():
    dev = relaxed_card("dev", 0.85)
    (dev,) = pr.order_by_quality(pr.rescore([dev], INDIA))
    assert dev["match_quality"] == "loose" and dev["score"] == pr.LOOSE_CEILING
    assert not pr.is_strong(dev)
    near = pr.person_from_card({"handle": "vc", "name": "Vc", "headline": "Seed investor in AI dev tools",
                                "location": "Berlin", "claimed": True, "match_score": 0.9, "why": []})
    near["relaxed"] = ["location"]
    (near,) = pr.order_by_quality(pr.rescore([near], INDIA))
    assert near["match_quality"] == "close" and near["score"] == pr.CLOSE_CEILING


def test_not_the_asked_role_is_never_a_close_match():
    sales = pr.person_from_external({"name": "Sal", "title": "Sales Manager", "company": "Investor Relations Inc",
                                     "location": "New Delhi, India", "linkedin_url": "https://linkedin.com/in/s", "score": 0.4}, 0)
    (sales,) = pr.order_by_quality(pr.rescore([sales], INDIA))
    assert sales["match_quality"] == "loose"


def test_a_broad_title_is_an_investor_only_at_a_fund():
    def fit(title, company):
        return pr.features({"headline": f"{title} at {company}", "sources": ["linkedin"], "location": "Pune, India"},
                           INDIA)["role_fit"]
    assert fit("Principal", "Java Capital") == 1.0
    assert fit("Managing Partner", "247VC") == 1.0
    assert fit("Principal", "Kearny Consulting") == pr.PARTIAL_ROLE
    assert fit("Investor Grievance Officer", "Dayco Securities") == 0.0
    assert fit("General Partner", "Together") == 1.0


def test_a_city_counts_as_being_in_its_country():
    feats = pr.features({"headline": "Seed investor", "location": "Gurgaon", "sources": ["card"]}, INDIA)
    assert feats["location_fit"] == 1.0
    abroad = pr.features({"headline": "Seed investor", "location": "Palo Alto", "sources": ["card"]}, INDIA)
    assert abroad["location_fit"] == 0.0


def test_a_linkedin_record_cannot_miss_a_topic():
    feats = pr.features({"headline": "General Partner at Fund X", "location": "Pune, India", "sources": ["linkedin"]}, INDIA)
    assert feats["topic_fit"] is None


FOUNDERS = parse_target_heuristic("founders building AI agents in India")


def test_a_strong_card_cards_found_strictly_beats_linkedin_records_that_cannot_show_the_topic():
    """Live, 2026-10-27: LinkedIn founders (topic unknown) were "exact" and pushed out every Card,
    including the founders Cards ranked first."""
    revanth = pr.person_from_card({"handle": "revanth", "name": "Revanth", "headline": "Co-Founder at Evolune EdgeTech",
                                   "location": "India", "claimed": True, "match_score": 0.838,
                                   "why": ["Matches your search terms", "Based in India"]})
    chandan = pr.person_from_card({"handle": "chandan", "name": "Chandan", "location": "Gurgaon", "claimed": True,
                                   "headline": "Building Verusa and zynd | AI Agents for Stablecoin Compliance",
                                   "match_score": 0.765, "why": ["Strong overall match for your query", "Role match"]})
    li = pr.person_from_external({"name": "Satwik", "title": "Co-Founder", "company": "strivelabs.ai",
                                  "location": "Chennai, India", "linkedin_url": "https://linkedin.com/in/s", "score": 0.8}, 0)
    ordered = pr.order_by_quality(pr.rescore([li, chandan, revanth], FOUNDERS))
    assert [p["name"] for p in ordered] == ["Revanth", "Chandan", "Satwik"]
    assert [p["match_quality"] for p in ordered] == ["exact", "exact", "close"]


def test_role_match_is_not_trusted_when_the_role_was_loosened():
    person = pr.person_from_card({"handle": "d", "name": "D", "headline": "Developer", "location": "India", "claimed": True,
                                  "match_score": 0.3, "why": ["Role match", "Not a founder (closest match)"]})
    assert pr.features(person, FOUNDERS)["role_fit"] == 0.0


def test_a_principal_consultant_is_not_an_investor_and_an_invest_fund_is_a_fund():
    def fit(title, company):
        return pr.features({"headline": f"{title} at {company}", "sources": ["linkedin"], "location": "Pune, India"},
                           INDIA)["role_fit"]
    assert fit("Principal Consultant", "Growexx") == 0.0
    assert fit("Managing Partner", "Speciale Invest") == 1.0
