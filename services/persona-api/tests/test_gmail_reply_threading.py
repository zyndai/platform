"""
Regression tests for thread-aware Gmail replies.

send_email used to have no way to attach a reply to an existing thread —
no `threadId` in the send body, no In-Reply-To/References headers — so
Gmail had to guess the right thread from the subject line alone, which
could misfile a reply into the wrong conversation. get_email_details now
also surfaces `thread_id` and `message_id_header` so a caller has what it
needs to reply correctly.
"""

from __future__ import annotations

import base64
from email import message_from_bytes
from unittest.mock import MagicMock, patch

from mcp.tools.google.gmail import get_email_details, send_email


def _decoded_headers(send_call_kwargs) -> dict:
    raw = send_call_kwargs["body"]["raw"]
    msg = message_from_bytes(base64.urlsafe_b64decode(raw))
    return dict(msg.items())


def test_send_email_without_reply_params_has_no_threading():
    fake_service = MagicMock()
    fake_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
        "id": "sent1", "threadId": "thread1",
    }

    with patch("mcp.tools.google.gmail._get_gmail_service", return_value=fake_service):
        result = send_email(user_id="u1", to="a@example.com", subject="Hi", body="hello")

    assert result["success"] is True
    send_call = fake_service.users.return_value.messages.return_value.send.call_args
    assert "threadId" not in send_call.kwargs["body"]
    headers = _decoded_headers(send_call.kwargs)
    assert "In-Reply-To" not in headers
    assert "References" not in headers


def test_send_email_with_reply_params_sets_thread_and_headers():
    fake_service = MagicMock()
    fake_service.users.return_value.messages.return_value.send.return_value.execute.return_value = {
        "id": "sent2", "threadId": "thread42",
    }

    with patch("mcp.tools.google.gmail._get_gmail_service", return_value=fake_service):
        result = send_email(
            user_id="u1",
            to="a@example.com",
            subject="Re: Q3 plan",
            body="Sounds good.",
            thread_id="thread42",
            in_reply_to_message_id="<orig-message-id@mail.gmail.com>",
        )

    assert result["success"] is True
    assert result["thread_id"] == "thread42"
    send_call = fake_service.users.return_value.messages.return_value.send.call_args
    assert send_call.kwargs["body"]["threadId"] == "thread42"
    headers = _decoded_headers(send_call.kwargs)
    assert headers["In-Reply-To"] == "<orig-message-id@mail.gmail.com>"
    assert headers["References"] == "<orig-message-id@mail.gmail.com>"


def test_get_email_details_exposes_thread_id_and_message_id_header():
    fake_service = MagicMock()
    fake_service.users.return_value.messages.return_value.get.return_value.execute.return_value = {
        "threadId": "thread42",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Q3 plan"},
                {"name": "From", "value": "boss@example.com"},
                {"name": "Date", "value": "Mon, 1 Jan 2026 10:00:00 +0000"},
                {"name": "Message-ID", "value": "<orig-message-id@mail.gmail.com>"},
            ],
            "body": {"data": base64.urlsafe_b64encode(b"body text").decode()},
        },
    }

    with patch("mcp.tools.google.gmail._get_gmail_service", return_value=fake_service):
        result = get_email_details(user_id="u1", message_id="msg1")

    assert result["success"] is True
    assert result["thread_id"] == "thread42"
    assert result["message_id_header"] == "<orig-message-id@mail.gmail.com>"
