"""
MCP Server — wraps the existing ContextAware framework and registers
all social/calendar/google/notion tools so the agent can discover and call them.
"""

import sys
from pathlib import Path

# Make the contextaware package importable
_ctx_path = str(Path(__file__).resolve().parent.parent.parent / "contextaware")
if _ctx_path not in sys.path:
    sys.path.insert(0, _ctx_path)

from ContextAware import ContextAware  # noqa: E402

# ── Import Social Tools ──
from mcp.tools.twitter import post_tweet, read_timeline, send_dm, read_dms
from mcp.tools.linkedin import post_to_linkedin, send_linkedin_dm, read_linkedin_dms

# ── Import Google Workspace Tools ──
from mcp.tools.google.calendar import create_event, list_events, delete_event
from mcp.tools.google.docs import create_document, append_to_document, read_document, list_google_docs, search_google_docs
from mcp.tools.google.gmail import search_emails, get_email_details, send_email, list_recent_threads
from mcp.tools.google.sheets import create_spreadsheet, append_to_sheet, read_sheet_values, search_spreadsheets
from mcp.tools.google.drive import create_drive_folder, list_drive_files, move_file_to_folder, list_files_in_folder

# ── Import Notion Tools ──
from mcp.tools.notion import (
    search_notion, 
    get_notion_database, 
    query_database, 
    create_notion_page, 
    update_notion_page, 
    get_notion_page_content, 
    create_notion_database, 
    append_to_notion_page
)

# ── Import Network Tools ──
from mcp.tools.zynd_network import search_zynd_personas, message_zynd_agent


def create_mcp_server(disable_security: bool = True) -> ContextAware:
    """
    Create and configure a ContextAware MCP server with all tools registered.
    """
    mcp = ContextAware()

    if disable_security:
        mcp.security(disable=True)

    # ── Twitter / X tools ────────────────────────────────────────────
    mcp.register(post_tweet, name="post_tweet", description="Post a tweet to X / Twitter")
    mcp.register(read_timeline, name="read_timeline", description="Read tweets from X timeline")
    mcp.register(send_dm, name="send_twitter_dm", description="Send a DM on X / Twitter")
    mcp.register(read_dms, name="read_twitter_dms", description="Read recent DMs on X / Twitter")

    # ── LinkedIn tools ───────────────────────────────────────────────
    mcp.register(post_to_linkedin, name="post_to_linkedin", description="Share a post on LinkedIn feed")
    mcp.register(send_linkedin_dm, name="send_linkedin_dm", description="[PLACEHOLDER] Send a LinkedIn DM")
    mcp.register(read_linkedin_dms, name="read_linkedin_dms", description="[PLACEHOLDER] Read LinkedIn DMs")

    # ── Google Calendar tools ────────────────────────────────────────
    mcp.register(create_event, name="create_calendar_event", description="Create an event on Google Calendar")
    mcp.register(list_events, name="list_calendar_events", description="List upcoming Google Calendar events")
    mcp.register(delete_event, name="delete_calendar_event", description="Delete a Google Calendar event")

    # ── Google Docs tools ──────────────────────────────────────────
    mcp.register(create_document, name="create_google_doc", description="Create a new Google Document")
    mcp.register(append_to_document, name="append_to_google_doc", description="Append text to a Google Document")
    mcp.register(read_document, name="read_google_doc", description="Read the entire content of a Google Document")
    mcp.register(list_google_docs, name="list_google_docs", description="List the 15 most recently modified Google Documents")
    mcp.register(search_google_docs, name="search_google_docs", description="Find Google Documents by name search")

    # ── Google Gmail tools ──────────────────────────────────────────
    mcp.register(search_emails, name="search_gmail_emails", description="Search Gmail for messages matching a query (e.g. from:someone)")
    mcp.register(get_email_details, name="get_gmail_email_details", description="Get the full body and headers of a specific email")
    mcp.register(send_email, name="send_gmail_email", description="Send an email through Gmail")
    mcp.register(list_recent_threads, name="list_recent_gmail_threads", description="List the most recent email conversations")

    # ── Google Sheets tools ──────────────────────────────────────────
    mcp.register(create_spreadsheet, name="create_google_sheet", description="Create a new Google Spreadsheet")
    mcp.register(append_to_sheet, name="append_to_google_sheet", description="Append rows of data/values to a specific sheet")
    mcp.register(read_sheet_values, name="read_google_sheet_values", description="Read a range of values (A1:C10) from a specific sheet")
    mcp.register(search_spreadsheets, name="search_google_spreadsheets", description="Find Google Spreadsheets by name search")

    # ── Google Drive tools ──────────────────────────────────────────
    mcp.register(create_drive_folder, name="create_google_drive_folder", description="Create a folder in Google Drive")
    mcp.register(list_drive_files, name="list_google_drive_files", description="List or search any file types in Google Drive (PDFs, Images, etc)")
    mcp.register(move_file_to_folder, name="move_google_drive_file", description="Organize files by moving them to a target folder")
    mcp.register(list_files_in_folder, name="list_google_drive_folder_contents", description="View all files within a specific Drive folder")

    # ── Notion tools ────────────────────────────────────────────────
    mcp.register(search_notion, name="search_notion", description="Search Notion for pages, databases, and workspace content")
    mcp.register(get_notion_database, name="get_notion_database", description="Retrieve the schema/properties of a Notion database")
    mcp.register(query_database, name="query_notion_database", description="Query a database with filters (status, date, etc) and sorting")
    mcp.register(create_notion_page, name="create_notion_page", description="Create a new page or database entry in Notion with smart property mapping")
    mcp.register(update_notion_page, name="update_notion_page", description="Update properties (Status, Due Date, etc) of an existing Notion page or database item")
    mcp.register(get_notion_page_content, name="get_notion_page_content", description="Read all blocks (text, TODOs, etc) of a Notion page with pagination")
    mcp.register(create_notion_database, name="create_notion_database", description="Create a new database with specific properties in a Notion page")
    mcp.register(append_to_notion_page, name="append_notion_blocks", description="Append rich blocks (headings, TODOs, bullets) to a Notion page")

    # ── Zynd Network interaction tools ─────────────────────────────
    mcp.register(search_zynd_personas, name="search_zynd_personas", description="Search the global open registry for other users' agents")
    mcp.register(message_zynd_agent, name="message_zynd_agent", description="Send a structured natural language request to another user's agent")

    # ── Default utility tools ──────────────────────
    mcp.register_default(names=["internet_search", "webpage_scrape", "get_current_time", "calculate"])

    return mcp

mcp_server = create_mcp_server()
