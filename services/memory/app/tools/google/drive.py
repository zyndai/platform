
import asyncio

from googleapiclient.discovery import build

from app.tools.google.common import get_google_creds


def _get_drive_service(user_id: str):
    creds = get_google_creds(user_id)
    return build("drive", "v3", credentials=creds)


async def list_google_drive_files(user_id: str, query: str = "", pageSize: int = 15) -> dict:
    def _list() -> dict:
        try:
            service = _get_drive_service(user_id)
            q = "trashed = false"
            if query:
                safe_query = query.replace("'", "\\'")
                q += f" and name contains '{safe_query}'"
            results = service.files().list(
                q=q, pageSize=pageSize, fields="files(id, name, mimeType, webViewLink, modifiedTime)"
            ).execute()
            return {"success": True, "files": results.get("files", []), "query": query}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_list)


async def create_google_drive_folder(user_id: str, folder_name: str, parent_id: str = None) -> dict:
    def _create() -> dict:
        try:
            service = _get_drive_service(user_id)
            file_metadata = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
            if parent_id:
                file_metadata["parents"] = [parent_id]
            file = service.files().create(body=file_metadata, fields="id, webViewLink").execute()
            return {"success": True, "id": file.get("id"), "link": file.get("webViewLink"), "name": folder_name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_create)


async def move_google_drive_file(user_id: str, file_id: str, folder_id: str) -> dict:
    def _move() -> dict:
        try:
            service = _get_drive_service(user_id)
            file = service.files().get(fileId=file_id, fields="parents").execute()
            previous_parents = ",".join(file.get("parents", []))
            new_file = service.files().update(
                fileId=file_id, addParents=folder_id, removeParents=previous_parents, fields="id, parents"
            ).execute()
            return {"success": True, "id": new_file.get("id"), "new_parents": new_file.get("parents")}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_move)


async def list_google_drive_folder_contents(user_id: str, folder_id: str) -> dict:
    def _list_contents() -> dict:
        try:
            service = _get_drive_service(user_id)
            q = f"'{folder_id}' in parents and trashed = false"
            results = service.files().list(q=q, fields="files(id, name, mimeType, webViewLink)").execute()
            return {"success": True, "files": results.get("files", []), "folder_id": folder_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_list_contents)
