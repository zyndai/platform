"""What each scraped source reveals to the create page before the card exists."""
from services.source_preview import build_preview


def test_linkedin_text_gives_identity_lines_and_posts():
    text = (
        "Name: Ada Lovelace\nHeadline: Engineer at Analytical Engines\n"
        "About: I write the first programs.\nLocation: London, UK\n"
    )
    stats = {
        "avatar": "https://cdn.example/ada.jpg",
        "posts": 12,
        "posts_raw": [
            {"excerpt": "Shipped a compiler pass that halves build times for everyone on the team."},
            {"excerpt": "ok"},  # too thin to land on the card, so too thin to preview
        ],
    }
    preview = build_preview("linkedin", text, stats)
    assert preview["name"] == "Ada Lovelace"
    assert preview["headline"] == "Engineer at Analytical Engines"
    assert preview["location"] == "London, UK"
    assert preview["bio"] == "I write the first programs."
    assert preview["avatar"] == "https://cdn.example/ada.jpg"
    assert preview["facts"] == ["12 posts"]
    assert preview["posts"] == ["Shipped a compiler pass that halves build times for everyone on the team."]


def test_github_user_gives_name_photo_and_facts():
    data = {
        "user": {"login": "ada", "name": "", "bio": "Compilers", "avatar_url": "https://avatars.example/ada", "followers": 40},
        "stats": {"total_repos": 9, "top_languages": ["Rust", "Go"]},
    }
    preview = build_preview("github", github=data)
    assert preview["name"] == "ada"  # falls back to the login when there is no display name
    assert preview["headline"] == "Compilers"
    assert preview["avatar"] == "https://avatars.example/ada"
    assert preview["facts"] == ["9 public repos", "Rust, Go", "40 followers"]


def test_unlabelled_website_text_becomes_a_clipped_bio():
    preview = build_preview("website", "word " * 200)
    assert "name" not in preview
    assert preview["bio"].endswith("…") and len(preview["bio"]) <= 240


def test_empty_values_are_dropped():
    assert build_preview("x", "", {"followers": "—", "posts": "—"}) == {}


def test_producthunt_preview_counts_launches_or_says_the_link_is_kept():
    launches = [{"name": "Orbit", "url": "https://www.producthunt.com/products/orbit"}]
    assert build_preview("producthunt", "Ada's launches", {"launches": launches})["facts"] == ["1 launch"]
    assert build_preview("producthunt", "", None) == {"facts": ["Link added to your card"]}
