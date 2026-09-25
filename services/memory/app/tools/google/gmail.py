
import asyncio
import base64
from email.mime.text import MIMEText

from googleapiclient.discovery import build

from app.tools.google.common import get_google_creds


def _get_gmail_service(user_id: str):
    creds = get_google_creds(user_id)
    return build("gmail", "v1", credentials=creds)


async def search_gmail_emails(user_id: str, query: str, max_results: int = 10) -> dict:
    def _search() -> dict:
        try:
            service = _get_gmail_service(user_id)
            results = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
            messages = results.get("messages", [])
            hydrated = []
            for msg in messages:
                m = service.users().messages().get(userId="me", id=msg["id"], format="minimal").execute()
                hydrated.append({"id": m["id"], "threadId": m["threadId"], "snippet": m.get("snippet", "")})
            return {"success": True, "messages": hydrated, "query": query}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_search)


async def get_gmail_email_details(user_id: str, message_id: str) -> dict:
    def _get() -> dict:
        try:
            service = _get_gmail_service(user_id)
            msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
            headers = msg.get("payload", {}).get("headers", [])
            subject = next((h["value"] for h in headers if h["name"].lower() == "subject"), "No Subject")
            sender = next((h["value"] for h in headers if h["name"].lower() == "from"), "Unknown")
            date = next((h["value"] for h in headers if h["name"].lower() == "date"), "")
            body = ""
            payload = msg.get("payload", {})
            if "parts" in payload:
                for part in payload["parts"]:
                    if part["mimeType"] == "text/plain":
                        data = part.get("body", {}).get("data", "")
                        body += base64.urlsafe_b64decode(data).decode("utf-8")
            else:
                data = payload.get("body", {}).get("data", "")
                if data:
                    body = base64.urlsafe_b64decode(data).decode("utf-8")
            return {
                "success": True, "id": message_id,
                "from": sender, "subject": subject, "date": date,
                "body": body[:5000],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_get)


async def send_gmail_email(user_id: str, to: str, subject: str, body: str) -> dict:
    def _send() -> dict:
        try:
            service = _get_gmail_service(user_id)
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
            sent_msg = service.users().messages().send(userId="me", body={"raw": raw_message}).execute()
            return {"success": True, "message_id": sent_msg["id"]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_send)


async def list_recent_gmail_threads(user_id: str, max_results: int = 10) -> dict:
    def _list() -> dict:
        try:
            service = _get_gmail_service(user_id)
            results = service.users().threads().list(userId="me", maxResults=max_results).execute()
            return {"success": True, "threads": results.get("threads", [])}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_list)
