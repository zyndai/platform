"""
Tests for trigger_scrape's URL-required contract (backend/api/linkedin.py).

With name guessing removed, a scrape with no profile_url param and no
stored profile_url must skip without scheduling any background task.
A stored profile_url is still used automatically.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import api.linkedin


class _Resp:
    def __init__(self, data):
        self.data = data


def _mock_supabase(rows=None):
    sb = MagicMock()
    chain = sb.table.return_value
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.upsert.return_value = chain
    chain.execute.return_value = _Resp(rows if rows is not None else [])
    return sb


def test_trigger_scrape_skips_without_any_profile_url():
    sb = _mock_supabase(rows=[])
    background = MagicMock()

    async def run():
        with patch("api.linkedin._get_supabase", return_value=sb):
            return await api.linkedin.trigger_scrape(
                background_tasks=background,
                user={"id": "u1", "user_metadata": {"full_name": "Jane Doe"}},
                force=False,
                profile_url=None,
                fast=False,
            )

    result = asyncio.run(run())
    assert result == {"status": "skipped", "reason": "no_profile_url"}
    background.add_task.assert_not_called()


def test_trigger_scrape_uses_stored_profile_url():
    sb = _mock_supabase(
        rows=[
            {
                "scraped_at": None,
                "profile_url": "https://www.linkedin.com/in/jane-doe",
                "raw_profile": {},
                "raw_posts": [],
            }
        ]
    )
    background = MagicMock()

    async def run():
        with patch("api.linkedin._get_supabase", return_value=sb):
            return await api.linkedin.trigger_scrape(
                background_tasks=background,
                user={"id": "u1", "user_metadata": {"full_name": "Jane Doe"}},
                force=False,
                profile_url=None,
                fast=False,
            )

    result = asyncio.run(run())
    assert result["status"] == "started"
    background.add_task.assert_called_once()
    args = background.add_task.call_args.args
    assert args[0] is api.linkedin._safe_scrape
    assert args[1] == "u1"
    assert args[2] == "https://www.linkedin.com/in/jane-doe"
