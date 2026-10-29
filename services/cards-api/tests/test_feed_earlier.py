"""Earlier items: when the recent feed is thin, older posts and GitHub activity follow it (never
ahead of it), marked `earlier`, with paging that stays consistent across the boundary."""
from datetime import timedelta

from services import feed
from tests.test_feed import NOW, ago, beacon, fact, page, row


def post(url, posted_days):
    return {"platform": "linkedin", "excerpt": f"post {url}", "url": url,
            "posted_at": (NOW - timedelta(days=posted_days)).date().isoformat()}


def release(event_id, days, repo="ana/lib"):
    return {"id": event_id, "type": "release", "repo": repo, "title": event_id, "url": f"https://github.com/{repo}", "at": ago(days=days)}


def test_older_posts_and_github_items_follow_the_recent_ones_and_are_marked_earlier():
    rows = [row("ana", writing_samples=[post("https://linkedin.com/p/old", 120)], zynd_memory=[fact("Fresh thing", approved_days=1)]),
            row("bob", writing_samples=[post("https://linkedin.com/p/older", 300)])]
    result = page(rows, github={"ana": [release("r1", 70)]})
    assert [(i["kind"], i["author"]["handle"], i["earlier"]) for i in result["items"]] == [
        ("working_on", "ana", False),
        ("github", "ana", True),          # newest first inside the earlier block
        ("post", "ana", True),
        ("post", "bob", True),
    ]


def test_earlier_items_never_outrank_recent_ones_even_when_the_author_is_a_connection():
    rows = [row("friend", writing_samples=[post("https://linkedin.com/p/a", 40)]),
            row("stranger", zynd_memory=[fact("Old-ish thing", approved_days=13)])]
    connections = {"friend": {"id": "c", "status": "accepted", "incoming": False}}
    assert [i["earlier"] for i in page(rows, connections=connections)["items"]] == [False, True]


def test_posts_older_than_a_year_and_posts_without_a_date_are_still_skipped():
    samples = [post("https://linkedin.com/p/ancient", 400),
               {"platform": "linkedin", "excerpt": "no date", "url": "https://linkedin.com/p/nodate", "posted_at": ""}]
    assert page([row("ana", writing_samples=samples)])["items"] == []
    assert [i["kind"] for i in page([row("ana", writing_samples=[post("https://linkedin.com/p/ok", 364)])])["items"]] == ["post"]


def test_the_asks_filter_has_no_earlier_items_and_the_network_filter_keeps_them_for_connections_only():
    rows = [row("ana", beacon=beacon(), writing_samples=[post("https://linkedin.com/p/a", 90)]),
            row("bob", writing_samples=[post("https://linkedin.com/p/b", 90)])]
    assert [i["kind"] for i in page(rows, filter="asks")["items"]] == ["ask"]
    connections = {"ana": {"id": "c", "status": "accepted", "incoming": False}}
    result = page(rows, connections=connections, filter="network")
    assert [(i["kind"], i["earlier"]) for i in result["items"]] == [("ask", False), ("post", True)]


def test_a_thin_feed_still_shows_something_from_earlier():
    (item,) = page([row("ana", writing_samples=[post("https://linkedin.com/p/a", 50)])])["items"]
    assert item["earlier"] is True and item["kind"] == "post"


def test_paging_is_consistent_across_the_recent_and_earlier_boundary():
    rows = [row(f"p{i}", zynd_memory=[fact(f"Thing {i}", approved_days=i % 9)]) for i in range(5)]
    rows += [row(f"e{i}", writing_samples=[post(f"https://linkedin.com/p/{i}", 40 + i * 10)]) for i in range(6)]
    assert len(page(rows, limit=50)["items"]) == 11
    for size in (2, 3, 4, 5, 7):
        seen, offset = [], 0
        while True:
            result = page(rows, limit=size, offset=offset)
            seen += [(i["id"], i["earlier"]) for i in result["items"]]
            if not result["next_cursor"]:
                break
            offset = feed.decode_cursor(result["next_cursor"])
        ids = [i for i, _ in seen]
        assert len(ids) == len(set(ids)) == 11
        flags = [e for _, e in seen]
        assert flags == sorted(flags)           # every recent item before every earlier one


def test_the_per_author_cap_also_holds_inside_the_earlier_block():
    rows = [row("busy", writing_samples=[post(f"https://linkedin.com/p/{i}", 40 + i) for i in range(5)])]
    rows += [row(f"o{i}", writing_samples=[post(f"https://linkedin.com/p/o{i}", 100)]) for i in range(3)]
    first = page(rows, limit=4)["items"]
    assert [i["author"]["handle"] for i in first].count("busy") == feed.PER_AUTHOR_CAP
