"""One re-rank for every source (people search plan, Phase 1.2-1.5)."""
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
    assert pr.label_quality([a, b]) == "" and (a["match_quality"], b["match_quality"]) == ("exact", "loose")
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
