"""
Google Docs & Drive MCP Tools

Registered via the ContextAware framework so the agent can:
  - create_document      — create a new Google Doc
  - append_to_document   — add text to an existing Google Doc
  - read_document        — get the content of a Google Doc

All functions accept a `user_id` to look up stored Google OAuth tokens.
Requires both Docs and Drive (drive.file) scopes.
"""

from mcp.tools.google.common import get_google_creds
from googleapiclient.discovery import build
import config


def _get_docs_service(user_id: str):
    """Build a Google Docs API service."""
    creds = get_google_creds(user_id)
    return build("docs", "v1", credentials=creds)


def _get_drive_service(user_id: str):
    """Build a Google Drive API service."""
    creds = get_google_creds(user_id)
    return build("drive", "v3", credentials=creds)


def create_document(user_id: str, title: str) -> dict:
    """
    Create a new Google Document.

    Args:
        user_id (str): The platform user ID
        title (str): Title of the new document

    Returns:
        dict: Created document info (id, link) or error
    """
    try:
        drive_svc = _get_drive_service(user_id)
        
        file_metadata = {
            "name": title,
            "mimeType": "application/vnd.google-apps.document"
        }
        
        doc = drive_svc.files().create(body=file_metadata, fields="id, name, webViewLink").execute()
        
        return {
            "success": True,
            "document_id": doc.get("id"),
            "title": doc.get("name"),
            "link": doc.get("webViewLink"),
        }
    except Exception as e:
        print(f"[docs] EXCEPTION in create_document: {str(e)}")
        return {"success": False, "error": str(e)}


def append_to_document(user_id: str, document_id: str, text: str) -> dict:
    """
    Append text to the end of a Google Document.

    Args:
        user_id (str): The platform user ID
        document_id (str): The ID of the document to update
        text (str): The text to append

    Returns:
        dict: Success status or error
    """
    try:
        docs_svc = _get_docs_service(user_id)
        
        # We use batchUpdate with insertText and endOfSegmentLocation
        requests = [
            {
                "insertText": {
                    "text": text,
                    "endOfSegmentLocation": {
                        "segmentId": "" # Empty string means main body
                    }
                }
            }
        ]
        
        docs_svc.documents().batchUpdate(
            documentId=document_id,
            body={"requests": requests}
        ).execute()
        
        return {"success": True, "document_id": document_id}
    except Exception as e:
        print(f"[docs] EXCEPTION in append_to_document: {str(e)}")
        return {"success": False, "error": str(e)}


def read_document(user_id: str, document_id: str) -> dict:
    """
    Read the content of a Google Document.

    Args:
        user_id (str): The platform user ID
        document_id (str): The ID of the document to read

    Returns:
        dict: The document content (metadata and plain text) or error
    """
    try:
        docs_svc = _get_docs_service(user_id)
        
        doc = docs_svc.documents().get(documentId=document_id).execute()
        
        # Helper to extract plain text from the document JSON structure
        # (Very basic extraction of 'textRun' elements)
        full_text = ""
        for element in doc.get("body", {}).get("content", []):
            if "paragraph" in element:
                for part in element["paragraph"].get("elements", []):
                    if "textRun" in part:
                        full_text += part["textRun"].get("content", "")
        
        return {"success": True, "title": doc.get("title"), "content": full_text}
    except Exception as e:
        print(f"[docs] EXCEPTION in read_document: {str(e)}")
        return {"success": False, "error": str(e)}


def list_google_docs(user_id: str, max_results: int = 15) -> dict:
    """
    List the most recently modified Google Documents.

    Args:
        user_id (str): The platform user ID
        max_results (int): Number of docs to return (max 50)

    Returns:
        dict: List of documents with names and IDs
    """
    try:
        drive_svc = _get_drive_service(user_id)
        
        # Query for only Google Docs, ordered by modification time
        q = "mimeType = 'application/vnd.google-apps.document' and trashed = false"
        results = drive_svc.files().list(
            q=q,
            pageSize=min(max_results, 50),
            fields="files(id, name, modifiedTime, webViewLink)",
            orderBy="modifiedTime desc"
        ).execute()
        
        files = results.get("files", [])
        return {
            "success": True,
            "documents": [
                {
                    "id": f["id"],
                    "name": f["name"],
                    "modified": f["modifiedTime"],
                    "link": f.get("webViewLink")
                } for f in files
            ]
        }
    except Exception as e:
        print(f"[docs] EXCEPTION in list_google_docs: {str(e)}")
        return {"success": False, "error": str(e)}


def search_google_docs(user_id: str, query: str) -> dict:
    """
    Search for Google Documents by name.

    Args:
        user_id (str): The platform user ID
        query (str): The name or part of the name to search for

    Returns:
        dict: Matching documents
    """
    try:
        drive_svc = _get_drive_service(user_id)
        
        # Escape single quotes in query
        safe_query = query.replace("'", "\\'")
        q = f"mimeType = 'application/vnd.google-apps.document' and name contains '{safe_query}' and trashed = false"
        
        results = drive_svc.files().list(
            q=q,
            fields="files(id, name, modifiedTime, webViewLink)",
        ).execute()
        
        files = results.get("files", [])
        return {
            "success": True,
            "query": query,
            "matches": [
                {
                    "id": f["id"],
                    "name": f["name"],
                    "modified": f["modifiedTime"],
                    "link": f.get("webViewLink")
                } for f in files
            ]
        }
    except Exception as e:
        print(f"[docs] EXCEPTION in search_google_docs: {str(e)}")
        return {"success": False, "error": str(e)}
