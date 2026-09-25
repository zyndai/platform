"""
Regression test for the LinkedIn recent-posts field mapping.

read_linkedin_profile used to read post text as `text`/`body`, but the
real harvestapi/linkedin-profile-posts actor puts it under `content` (and
the timestamp under a nested `postedAt.date`, the URL under `linkedinUrl`,
reactions under `engagement.likes`). That mismatch meant posts always came
back with a timestamp but empty text. This locks in the corrected mapping.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import config
from mcp.tools.linkedin import read_linkedin_profile


class _Resp:
    def __init__(self, data):
        self.data = data


def _mock_supabase(row: dict):
    sb = MagicMock()
    chain = sb.table.return_value
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.execute.return_value = _Resp([row])
    return sb


def test_real_harvestapi_post_shape_maps_content_and_timestamp():
    raw_posts = [{
        "content": "Excited to announce our seed round!",
        "postedAt": {"timestamp": 1732000000000, "date": "2026-01-15T10:00:00.000Z"},
        "linkedinUrl": "https://www.linkedin.com/posts/example_activity-123",
        "engagement": {"likes": 42, "reactions": [{"type": "LIKE", "count": 30}]},
    }]
    sb = _mock_supabase({
        "raw_profile": {"headline": "Founder"},
        "raw_posts": raw_posts,
        "scraped_at": "2026-01-15T12:00:00Z",
        "profile_url": "https://www.linkedin.com/in/example",
    })

    with patch.object(config, "get_supabase", return_value=sb):
        result = read_linkedin_profile(user_id="u1")

    assert result["success"] is True
    post = result["recent_posts"][0]
    assert post["text"] == "Excited to announce our seed round!"
    assert post["posted_at"] == "2026-01-15T10:00:00.000Z"
    assert post["url"] == "https://www.linkedin.com/posts/example_activity-123"
    assert post["reaction_count"] == 42


def test_legacy_field_names_still_fall_back():
    # Guard against removing the old fallback keys outright — if an older
    # actor version (or cached data) ever used them, they should still work.
    raw_posts = [{
        "text": "Old-shape post",
        "postedAt": "2026-01-01T00:00:00Z",
        "postUrl": "https://www.linkedin.com/posts/old",
        "reactionCount": 7,
    }]
    sb = _mock_supabase({
        "raw_profile": {"headline": "Founder"},
        "raw_posts": raw_posts,
        "scraped_at": "2026-01-01T00:00:00Z",
        "profile_url": "https://www.linkedin.com/in/example",
    })

    with patch.object(config, "get_supabase", return_value=sb):
        result = read_linkedin_profile(user_id="u1")

    post = result["recent_posts"][0]
    assert post["text"] == "Old-shape post"
    assert post["posted_at"] == "2026-01-01T00:00:00Z"
    assert post["url"] == "https://www.linkedin.com/posts/old"
    assert post["reaction_count"] == 7
