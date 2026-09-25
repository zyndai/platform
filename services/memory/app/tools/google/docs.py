
import asyncio

from googleapiclient.discovery import build

from app.tools.google.common import get_google_creds


def _get_docs_service(user_id: str):
    creds = get_google_creds(user_id)
    return build("docs", "v1", credentials=creds)


def _get_drive_service(user_id: str):
    creds = get_google_creds(user_id)
    return build("drive", "v3", credentials=creds)


async def create_google_doc(user_id: str, title: str) -> dict:
    def _create() -> dict:
        try:
            drive_svc = _get_drive_service(user_id)
            file_metadata = {"name": title, "mimeType": "application/vnd.google-apps.document"}
            doc = drive_svc.files().create(body=file_metadata, fields="id, name, webViewLink").execute()
            return {
                "success": True,
                "document_id": doc.get("id"),
                "title": doc.get("name"),
                "link": doc.get("webViewLink"),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_create)


async def append_to_google_doc(user_id: str, document_id: str, text: str) -> dict:
    def _append() -> dict:
        try:
            docs_svc = _get_docs_service(user_id)
            requests = [{
                "insertText": {
                    "text": text,
                    "endOfSegmentLocation": {"segmentId": ""}
                }
            }]
            docs_svc.documents().batchUpdate(
                documentId=document_id, body={"requests": requests}
            ).execute()
            return {"success": True, "document_id": document_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_append)


async def read_google_doc(user_id: str, document_id: str) -> dict:
    def _read() -> dict:
        try:
            docs_svc = _get_docs_service(user_id)
            doc = docs_svc.documents().get(documentId=document_id).execute()
            full_text = ""
            for element in doc.get("body", {}).get("content", []):
                if "paragraph" in element:
                    for part in element["paragraph"].get("elements", []):
                        if "textRun" in part:
                            full_text += part["textRun"].get("content", "")
            return {"success": True, "title": doc.get("title"), "content": full_text}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_read)


async def list_google_docs(user_id: str, max_results: int = 15) -> dict:
    def _list() -> dict:
        try:
            drive_svc = _get_drive_service(user_id)
            q = "mimeType = 'application/vnd.google-apps.document' and trashed = false"
            results = drive_svc.files().list(
                q=q,
                pageSize=min(max_results, 50),
                fields="files(id, name, modifiedTime, webViewLink)",
                orderBy="modifiedTime desc",
            ).execute()
            files = results.get("files", [])
            return {
                "success": True,
                "documents": [
                    {"id": f["id"], "name": f["name"], "modified": f["modifiedTime"], "link": f.get("webViewLink")}
                    for f in files
                ],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_list)


async def search_google_docs(user_id: str, query: str) -> dict:
    def _search() -> dict:
        try:
            drive_svc = _get_drive_service(user_id)
            safe_query = query.replace("'", "\\'")
            q = f"mimeType = 'application/vnd.google-apps.document' and name contains '{safe_query}' and trashed = false"
            results = drive_svc.files().list(q=q, fields="files(id, name, modifiedTime, webViewLink)").execute()
            files = results.get("files", [])
            return {
                "success": True,
                "query": query,
                "matches": [
                    {"id": f["id"], "name": f["name"], "modified": f["modifiedTime"], "link": f.get("webViewLink")}
                    for f in files
                ],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_search)


async def replace_document_body(user_id: str, document_id: str, text: str) -> dict:
    def _replace() -> dict:
        try:
            docs_svc = _get_docs_service(user_id)
            doc = docs_svc.documents().get(documentId=document_id).execute()
            body_content = doc.get("body", {}).get("content", [])
            end_index = body_content[-1].get("endIndex", 1) if body_content else 1

            requests = []
            if end_index > 2:
                requests.append({
                    "deleteContentRange": {
                        "range": {"startIndex": 1, "endIndex": end_index - 1}
                    }
                })
            if text:
                requests.append({
                    "insertText": {"location": {"index": 1}, "text": text}
                })

            if requests:
                docs_svc.documents().batchUpdate(
                    documentId=document_id, body={"requests": requests}
                ).execute()
            return {"success": True, "document_id": document_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_replace)
