"""
Tests for the page publisher service, API, and MCP tools.

These tests mock the Supabase client so they don't require a live DB.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import config
from mcp.tools.publish_page import list_my_pages, publish_page
from services.page_publisher import (
    create_page,
    delete_page,
    get_page_public,
    list_pages,
)


class _Resp:
    def __init__(self, data):
        self.data = data


def _mock_supabase(rows=None, single=None, insert_data=None):
    """Build a minimal fake supabase client."""
    sb = MagicMock()
    chain = sb.table.return_value
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    chain.delete.return_value = chain
    chain.maybe_single.return_value = chain

    if single is not None:
        chain.execute.return_value = _Resp(single)
    elif rows is not None:
        chain.execute.return_value = _Resp(rows)
    else:
        chain.execute.return_value = _Resp(None)

    insert_chain = MagicMock()
    insert_chain.execute.return_value = _Resp(insert_data)
    chain.insert.return_value = insert_chain

    return sb


class TestPagePublisher:
    def test_create_page_requires_user_id(self):
        result = create_page(user_id="", content="hello")
        assert result["success"] is False
        assert "user_id" in result["error"].lower()

    def test_create_page_content_too_long(self):
        result = create_page(user_id="u1", content="x" * 2_000_000)
        assert result["success"] is False
        assert "too long" in result["error"].lower()

    def test_create_page_valid(self):
        sb = _mock_supabase(insert_data=[{"slug": "abc123"}])
        with patch.object(config, "get_supabase", return_value=sb):
            result = create_page(
                user_id="u1",
                content="<h1>hi</h1>",
                title="My page",
                format="html",
            )

        assert result["success"] is True
        assert result["title"] == "My page"
        assert result["format"] == "html"
        assert "slug" in result
        assert "url" in result
        assert "/pages/" in result["url"]

        insert_call = sb.table.return_value.insert.call_args
        args = insert_call[0][0]
        assert args["user_id"] == "u1"
        assert args["format"] == "html"
        assert args["visibility"] == "unlisted"

    def test_create_page_normalizes_md_alias(self):
        sb = _mock_supabase(insert_data=[{"slug": "md123"}])
        with patch.object(config, "get_supabase", return_value=sb):
            result = create_page(user_id="u1", content="# hi", format="md")
        assert result["success"] is True
        assert result["format"] == "markdown"

    def test_create_page_retries_on_duplicate_slug(self):
        # First two inserts raise a duplicate-key error, third succeeds.
        sb = _mock_supabase()
        calls = []

        def side_effect():
            calls.append(1)
            if len(calls) <= 2:
                raise Exception("duplicate key value violates unique constraint")
            return MagicMock(data={"slug": "abc123", "title": "t"})

        sb.table.return_value.insert.return_value.execute.side_effect = side_effect

        with patch.object(config, "get_supabase", return_value=sb):
            result = create_page(user_id="u1", content="x")

        assert result["success"] is True
        assert len(calls) == 3

    def test_get_page_public_returns_unlisted(self):
        sb = _mock_supabase(single={
            "slug": "abc",
            "title": "T",
            "format": "html",
            "content": "<p>x</p>",
            "visibility": "unlisted",
        })
        with patch.object(config, "get_supabase", return_value=sb):
            page = get_page_public("abc")
        assert page is not None
        assert page["slug"] == "abc"
        assert page["format"] == "html"

    def test_get_page_public_hides_private(self):
        sb = _mock_supabase(single={
            "slug": "abc",
            "title": "T",
            "format": "html",
            "content": "x",
            "visibility": "private",
        })
        with patch.object(config, "get_supabase", return_value=sb):
            page = get_page_public("abc")
        assert page is None

    def test_list_pages_filters_by_user(self):
        sb = _mock_supabase(rows=[
            {"slug": "a", "title": "A", "format": "html", "visibility": "unlisted"},
        ])
        with patch.object(config, "get_supabase", return_value=sb):
            pages = list_pages(user_id="u1")
        assert len(pages) == 1
        assert pages[0]["slug"] == "a"
        sb.table.return_value.eq.assert_any_call("user_id", "u1")

    def test_delete_page_scoped_to_user(self):
        sb = _mock_supabase()
        with patch.object(config, "get_supabase", return_value=sb):
            result = delete_page(user_id="u1", slug="abc")
        assert result["success"] is True
        sb.table.return_value.delete.return_value.eq.assert_any_call("slug", "abc")
        sb.table.return_value.delete.return_value.eq.assert_any_call("user_id", "u1")


class TestPublishPageTool:
    def test_publish_page_delegates_to_service(self):
        sb = _mock_supabase(insert_data=[{"slug": "tool123"}])
        with patch.object(config, "get_supabase", return_value=sb):
            result = publish_page(
                user_id="u1",
                content="# Hello",
                title="Hello",
                format="markdown",
            )
        assert result["success"] is True
        assert result["format"] == "markdown"

    def test_list_my_pages_returns_count(self):
        sb = _mock_supabase(rows=[
            {"slug": "a", "title": "A", "format": "html", "visibility": "unlisted"},
            {"slug": "b", "title": "B", "format": "markdown", "visibility": "public"},
        ])
        with patch.object(config, "get_supabase", return_value=sb):
            result = list_my_pages(user_id="u1")
        assert result["success"] is True
        assert result["count"] == 2
        assert len(result["pages"]) == 2


class TestPublishedPagesAPI:
    def test_create_page_request_validation(self):
        from api.pages import CreatePageRequest
        body = CreatePageRequest(content="<p>hi</p>", title="Hi", format="html")
        assert body.format == "html"

    def test_create_page_request_rejects_bad_format(self):
        from api.pages import CreatePageRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CreatePageRequest(content="x", format="docx")  # type: ignore[call-arg]
