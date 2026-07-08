
import asyncio

from googleapiclient.discovery import build

from app.tools.google.common import get_google_creds


def _get_sheets_service(user_id: str):
    creds = get_google_creds(user_id)
    return build("sheets", "v4", credentials=creds)


async def create_google_sheet(user_id: str, title: str) -> dict:
    def _create() -> dict:
        try:
            service = _get_sheets_service(user_id)
            spreadsheet = {"properties": {"title": title}}
            res = service.spreadsheets().create(body=spreadsheet, fields="spreadsheetId, spreadsheetUrl").execute()
            return {"success": True, "spreadsheet_id": res.get("spreadsheetId"), "url": res.get("spreadsheetUrl"), "title": title}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_create)


async def append_to_google_sheet(user_id: str, spreadsheet_id: str, values: list[list], range_name: str = "Sheet1!A1") -> dict:
    def _append() -> dict:
        try:
            service = _get_sheets_service(user_id)
            body = {"values": values}
            res = service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body=body,
            ).execute()
            return {"success": True, "spreadsheet_id": spreadsheet_id, "updates": res.get("updates", {})}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_append)


async def read_google_sheet_values(user_id: str, spreadsheet_id: str, range_name: str = "Sheet1!A:Z") -> dict:
    def _read() -> dict:
        try:
            service = _get_sheets_service(user_id)
            result = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
            return {"success": True, "values": result.get("values", []), "spreadsheet_id": spreadsheet_id, "range": range_name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_read)


async def search_google_spreadsheets(user_id: str, query: str = "") -> dict:
    def _search() -> dict:
        try:
            from googleapiclient.discovery import build as _build
            from app.tools.google.common import get_google_creds as _creds
            creds = _creds(user_id)
            drive_svc = _build("drive", "v3", credentials=creds)
            q = "mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
            if query:
                safe_query = query.replace("'", "\\'")
                q += f" and name contains '{safe_query}'"
            results = drive_svc.files().list(q=q, fields="files(id, name, webViewLink)").execute()
            files = results.get("files", [])
            return {"success": True, "spreadsheets": [{"id": f["id"], "name": f["name"], "link": f["webViewLink"]} for f in files]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await asyncio.to_thread(_search)
