"""
Google Drive Management Tools

Operates under the `drive.file` scope: the agent can only see, organize,
and modify files it created itself (or that the user explicitly opened
for it via a Picker). The user's other Drive files are invisible by design.
"""

from googleapiclient.discovery import build
from mcp.tools.google.common import get_google_creds
from mcp.tools.error_utils import friendly_error

def _get_drive_service(user_id: str):
    """Build a Google Drive API service."""
    creds = get_google_creds(user_id)
    return build("drive", "v3", credentials=creds)

def list_drive_files(user_id: str, query: str = "", pageSize: int = 15) -> dict:
    """
    List files the agent itself created in Google Drive.

    The `drive.file` scope means the user's other files are not visible —
    only what this app created or what the user explicitly opened with it.

    Args:
        user_id: Platform user ID
        query: Optional Drive search query (matched against name)
        pageSize: How many files to return
    """
    try:
        service = _get_drive_service(user_id)
        
        q = "trashed = false"
        if query:
            safe_query = query.replace("'", "\\'")
            q += f" and name contains '{safe_query}'"
            
        results = service.files().list(
            q=q,
            pageSize=pageSize,
            fields="files(id, name, mimeType, webViewLink, modifiedTime)"
        ).execute()
        
        files = results.get("files", [])
        return {
            "success": True,
            "files": files,
            "query": query
        }
    except Exception as e:
        return friendly_error("list your Drive files", e)

def create_drive_folder(user_id: str, folder_name: str, parent_id: str = None) -> dict:
    """
    Create a new folder in Google Drive.
    """
    try:
        service = _get_drive_service(user_id)
        
        file_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder"
        }
        if parent_id:
            file_metadata["parents"] = [parent_id]
            
        file = service.files().create(body=file_metadata, fields="id, webViewLink").execute()
        return {
            "success": True,
            "id": file.get("id"),
            "link": file.get("webViewLink"),
            "name": folder_name
        }
    except Exception as e:
        return friendly_error("create the Drive folder", e)

def move_file_to_folder(user_id: str, file_id: str, folder_id: str) -> dict:
    """
    Move an existing file or folder to a new parent folder.
    """
    try:
        service = _get_drive_service(user_id)
        
        # 1. Retrieve the file to find existing parents
        file = service.files().get(fileId=file_id, fields="parents").execute()
        previous_parents = ",".join(file.get("parents", []))
        
        # 2. Update the file to add new parent and remove old parents
        new_file = service.files().update(
            fileId=file_id,
            addParents=folder_id,
            removeParents=previous_parents,
            fields="id, parents"
        ).execute()
        
        return {
            "success": True,
            "id": new_file.get("id"),
            "new_parents": new_file.get("parents")
        }
    except Exception as e:
        return friendly_error("move the file", e)

def list_files_in_folder(user_id: str, folder_id: str) -> dict:
    """
    List files specifically within a folder.
    """
    try:
        service = _get_drive_service(user_id)
        q = f"'{folder_id}' in parents and trashed = false"
        results = service.files().list(q=q, fields="files(id, name, mimeType, webViewLink)").execute()
        files = results.get("files", [])
        return {"success": True, "files": files, "folder_id": folder_id}
    except Exception as e:
        return friendly_error("list the folder contents", e)
