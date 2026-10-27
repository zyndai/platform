"""Proof read off a person's own pages: newsletter posts and design-portfolio tiles."""
from scraping import sites

BEHANCE = """
[![Image 1: Avatar profile image](https://mir-s3-cdn-cf.behance.net/team/138/73.53f4ead6562cf.png)](https://www.behance.net/ada)
[![Image 2](https://a5.behance.net/abc/img/galleries/icons/ribbons/1x/network.png?cb=1)](http://www.behance.net/)
[![Image 9: Brand system for Orbit](https://mir-s3-cdn-cf.behance.net/projects/202/aaa111.jpg)](https://www.behance.net/gallery/111/Brand-system-for-Orbit)
[![Image 10: Poster series](https://mir-s3-cdn-cf.behance.net/projects/202/bbb222.jpg)](https://www.behance.net/gallery/222/Poster-series)
[![Image 11](https://pps.services.adobe.com/api/profile/x/image/50)by: Someone](https://www.behance.net/someone)
[![Image 12: Poster series again](https://mir-s3-cdn-cf.behance.net/projects/202/bbb222.jpg)](https://www.behance.net/gallery/222/Poster-series)
"""

DRIBBBLE = """
![Image 3: Dribbble](https://cdn.dribbble.com/users/39/avatars/normal/a094.png?1769457020)
![Image 6: Reimagine a brand dribbble warm up](https://cdn.dribbble.com/userupload/47508438/file/4a16.png?format=webp&resize=400x300)6  [View Reimagine a brand](https://dribbble.com/shots/27314225-Reimagine-a-brand)
![Image 7: A promo banner](https://cdn.dribbble.com/assets/announcements/tag-2x.png)
![Image 8: Easter eggs](https://cdn.dribbble.com/userupload/47123809/file/c19f.png?format=webp)9+  [View Easter eggs](https://dribbble.com/shots/27201957-Easter-eggs)
"""

SUBSTACK = """
[Home](https://ada.substack.com/)
[How to tell if a startup has a moat](https://ada.substack.com/p/how-to-tell-if-a-startup-has-a-moat)
[A framework for assessing whether the company is built to last](https://ada.substack.com/p/how-to-tell-if-a-startup-has-a-moat)
Oct 13•[Dan Hockenmaier](https://substack.com/@danhock)
[A second post about hiring well](https://ada.substack.com/p/a-second-post?utm_source=archive)
[Someone else's recommended post](https://other.substack.com/p/someone-elses-post)
"""


def test_behance_gallery_keeps_project_covers_only():
    gallery = sites.extract_gallery(BEHANCE, "https://www.behance.net/ada")
    assert [g["title"] for g in gallery] == ["Brand system for Orbit", "Poster series"]  # no avatar, icon, other designer or repeat
    assert gallery[0] == {
        "title": "Brand system for Orbit",
        "url": "https://www.behance.net/gallery/111/Brand-system-for-Orbit",
        "image_url": "https://mir-s3-cdn-cf.behance.net/projects/202/aaa111.jpg",
        "source": "behance",
    }


def test_dribbble_gallery_pairs_each_shot_with_its_view_link():
    gallery = sites.extract_gallery(DRIBBBLE, "https://dribbble.com/ada")
    assert [g["url"] for g in gallery] == [
        "https://dribbble.com/shots/27314225-Reimagine-a-brand",
        "https://dribbble.com/shots/27201957-Easter-eggs",
    ]
    assert gallery[0]["title"] == "Reimagine a brand dribbble warm up"
    assert all(g["image_url"].startswith("https://cdn.dribbble.com/userupload/") for g in gallery)


def test_gallery_is_capped_and_ignores_other_sites():
    many = "\n".join(
        f"[![Image {i}: Work {i}](https://mir-s3-cdn-cf.behance.net/projects/202/{i}.jpg)](https://www.behance.net/gallery/{i}/Work-{i})"
        for i in range(20)
    )
    assert len(sites.extract_gallery(many, "https://www.behance.net/ada")) == sites.GALLERY_ITEMS
    assert sites.extract_gallery(many, "https://example.com/portfolio") == []


def test_substack_posts_join_title_and_subtitle_and_stay_on_the_newsletter():
    posts = sites.extract_posts(SUBSTACK, "https://ada.substack.com/archive")
    assert posts == [
        {"platform": "substack", "excerpt": "How to tell if a startup has a moat — A framework for assessing whether the company is built to last",
         "url": "https://ada.substack.com/p/how-to-tell-if-a-startup-has-a-moat", "posted_at": ""},
        {"platform": "substack", "excerpt": "A second post about hiring well", "url": "https://ada.substack.com/p/a-second-post", "posted_at": ""},
    ]


def test_a_custom_domain_substack_is_recognised_from_its_page():
    page = "![x](https://substackcdn.com/image/fetch/a.png)\n[A post worth reading twice](https://news.example.com/p/a-post-worth-reading)"
    assert sites.extract_posts(page, "https://news.example.com/archive")[0]["url"] == "https://news.example.com/p/a-post-worth-reading"
    assert sites.extract_posts("[A post worth reading twice](https://news.example.com/p/a-post)", "https://news.example.com") == []


def test_medium_posts_need_the_hex_suffix_medium_gives_every_story():
    page = (
        "[Why small teams ship faster](https://medium.com/@ada/why-small-teams-ship-faster-3f9a1c2b7d4e?source=profile)\n"
        "[About this publication](https://medium.com/@ada/about)\n"
    )
    posts = sites.extract_posts(page, "https://medium.com/@ada")
    assert [p["url"] for p in posts] == ["https://medium.com/@ada/why-small-teams-ship-faster-3f9a1c2b7d4e"]
    assert posts[0]["platform"] == "medium"


def test_source_kinds():
    assert sites.is_writing_url("https://ada.substack.com") and sites.is_writing_url("https://dev.to/ada")
    assert not sites.is_writing_url("https://example.com/blog")
    assert sites.portfolio_platform("https://www.behance.net/ada") == "behance"
    assert sites.portfolio_platform("https://dribbble.com/ada") == "dribbble"
    assert sites.portfolio_platform("https://example.com") is None
