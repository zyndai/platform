"""
Gmail MCP Tools
Allows the agent to search, read, and send emails.
"""

from googleapiclient.discovery import build
from mcp.tools.google.common import get_google_creds
from mcp.tools.error_utils import friendly_error
import base64
from email.mime.text import MIMEText

def _get_gmail_service(user_id: str):
    """Build a Gmail API service."""
    creds = get_google_creds(user_id)
    return build("gmail", "v1", credentials=creds)

def search_emails(user_id: str, query: str, max_results: int = 10) -> dict:
    """
    Search for email messages matching a query.
    
    Args:
        user_id: Platform user ID
        query: Gmail search query (e.g. "from:boss", "is:unread")
        max_results: Max messages to return
    """
    try:
        service = _get_gmail_service(user_id)
        results = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        messages = results.get("messages", [])
        
        # Hydrate messages with snippets
        hydrated = []
        for msg in messages:
            m = service.users().messages().get(userId="me", id=msg["id"], format="minimal").execute()
            hydrated.append({
                "id": m["id"],
                "threadId": m["threadId"],
                "snippet": m.get("snippet", ""),
            })
            
        return {"success": True, "messages": hydrated, "query": query}
    except Exception as e:
        print(f"[gmail] Error searching: {e}")
        return friendly_error("search your emails", e)

def get_email_details(user_id: str, message_id: str) -> dict:
    """
    Get full details of a specific email message.

    Returns `thread_id` and `message_id_header` (the RFC Message-ID header,
    distinct from Gmail's own `id`) alongside the body — pass BOTH of those
    to `send_email`'s `thread_id`/`in_reply_to_message_id` when replying so
    the reply lands in this exact thread instead of Gmail guessing from the
    subject line alone (which can attach it to the wrong thread when
    subjects repeat).
    """
    try:
        service = _get_gmail_service(user_id)
        msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()

        headers = msg.get("payload", {}).get("headers", [])
        subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "No Subject")
        sender = next((h["value"] for h in headers if h["name"].lower() == "from"), "Unknown")
        date = next((h["value"] for h in headers if h["name"].lower() == "date"), "")
        message_id_header = next((h["value"] for h in headers if h["name"].lower() == "message-id"), "")

        # Basic body extraction (plain text)
        body = ""
        payload = msg.get("payload", {})
        if "parts" in payload:
            for part in payload["parts"]:
                if part["mimeType"] == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    body += base64.urlsafe_b64decode(data).decode('utf-8')
        else:
            data = payload.get("body", {}).get("data", "")
            if data:
                body = base64.urlsafe_b64decode(data).decode('utf-8')

        return {
            "success": True,
            "id": message_id,
            "thread_id": msg.get("threadId", ""),
            "message_id_header": message_id_header,
            "from": sender,
            "subject": subject,
            "date": date,
            "body": body[:5000] # Limit to avoid huge tokens
        }
    except Exception as e:
        return friendly_error("read that email", e)

def send_email(
    user_id: str,
    to: str,
    subject: str,
    body: str,
    thread_id: str = "",
    in_reply_to_message_id: str = "",
) -> dict:
    """
    Send an email message.

    To REPLY within an existing conversation instead of starting a new one,
    first call `get_email_details` on the message you're replying to, then
    pass its `thread_id` and `message_id_header` here as `thread_id` and
    `in_reply_to_message_id`. Without both of these, Gmail has to guess the
    right thread from the subject line alone, which can misfile the reply
    into an unrelated thread that happens to share a similar subject.
    """
    try:
        service = _get_gmail_service(user_id)
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        if in_reply_to_message_id:
            message["In-Reply-To"] = in_reply_to_message_id
            message["References"] = in_reply_to_message_id

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

        send_body: dict = {"raw": raw_message}
        if thread_id:
            send_body["threadId"] = thread_id

        sent_msg = service.users().messages().send(userId="me", body=send_body).execute()
        return {"success": True, "message_id": sent_msg["id"], "thread_id": sent_msg.get("threadId", "")}
    except Exception as e:
        return friendly_error("send the email", e)

def list_recent_threads(user_id: str, max_results: int = 10) -> dict:
    """
    List recent email threads.
    """
    try:
        service = _get_gmail_service(user_id)
        results = service.users().threads().list(userId="me", maxResults=max_results).execute()
        threads = results.get("threads", [])
        return {"success": True, "threads": threads}
    except Exception as e:
        return friendly_error("list recent email threads", e)
