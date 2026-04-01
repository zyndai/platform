"""
Google Sheets MCP Tools
Allows the agent to manage spreadsheets and log data.
"""

from googleapiclient.discovery import build
from mcp.tools.google.common import get_google_creds

def _get_sheets_service(user_id: str):
    """Build a Google Sheets API service."""
    creds = get_google_creds(user_id)
    return build("sheets", "v4", credentials=creds)

def create_spreadsheet(user_id: str, title: str) -> dict:
    """
    Create a new Google Spreadsheet.
    """
    try:
        service = _get_sheets_service(user_id)
        spreadsheet = {
            "properties": {"title": title}
        }
        res = service.spreadsheets().create(body=spreadsheet, fields="spreadsheetId, spreadsheetUrl").execute()
        return {
            "success": True,
            "spreadsheet_id": res.get("spreadsheetId"),
            "url": res.get("spreadsheetUrl"),
            "title": title
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def append_to_sheet(user_id: str, spreadsheet_id: str, values: list[list], range_name: str = "Sheet1!A1") -> dict:
    """
    Append rows of data to a spreadsheet.
    
    Args:
        user_id: Platform user ID
        spreadsheet_id: The ID of the spreadsheet
        values: A list of lists representing rows (e.g. [["Date", "Expense"], ["2024-04-01", "100"]])
        range_name: The sheet and range to start appending (default is Sheet1!A1)
    """
    try:
        service = _get_sheets_service(user_id)
        body = {
            "values": values
        }
        res = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body
        ).execute()
        
        return {
            "success": True,
            "spreadsheet_id": spreadsheet_id,
            "updates": res.get("updates", {})
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def read_sheet_values(user_id: str, spreadsheet_id: str, range_name: str = "Sheet1!A:Z") -> dict:
    """
    Read values from a specific sheet range.
    """
    try:
        service = _get_sheets_service(user_id)
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        
        values = result.get("values", [])
        return {
            "success": True,
            "values": values,
            "spreadsheet_id": spreadsheet_id,
            "range": range_name
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def search_spreadsheets(user_id: str, query: str = "") -> dict:
    """
    Find spreadsheets by name in Google Drive.
    """
    try:
        # We use Drive API to search for spreadsheets
        from mcp.tools.google.docs import _get_drive_service
        drive_svc = _get_drive_service(user_id)
        
        q = "mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
        if query:
            safe_query = query.replace("'", "\\'")
            q += f" and name contains '{safe_query}'"
            
        results = drive_svc.files().list(q=q, fields="files(id, name, webViewLink)").execute()
        files = results.get("files", [])
        
        return {
            "success": True,
            "spreadsheets": [
                {"id": f["id"], "name": f["name"], "link": f["webViewLink"]} for f in files
            ]
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
