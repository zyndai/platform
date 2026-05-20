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
from mcp.tools.zynd_network import (
    search_zynd_personas,
    get_persona_profile,
    list_my_connections,
    request_connection,
    check_connection_status,
    message_zynd_agent,
    read_agent_channel,
)

# ── Import Zynd Network Services Tools ──
from mcp.tools.zynd_services import (
    search_zynd_services,
    get_zynd_service_card,
    call_zynd_service,
)

# ── Import Scheduling Tools ──
from mcp.tools.scheduling import (
    propose_meeting,
    propose_group_meeting,
    respond_to_meeting,
    list_pending_meetings,
)

# ── Import Brief Tools ──
# Principal-private; never added to any external allowlist.
from mcp.tools.brief import (
    read_my_brief,
    append_to_my_brief,
    replace_my_brief,
    clear_my_brief,
    add_todo,
)


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
    mcp.register(list_google_docs, name="list_google_docs", description="List the most recently modified Google Documents the agent itself created (drive.file scope — the user's other docs are not visible)")
    mcp.register(search_google_docs, name="search_google_docs", description="Find Google Documents by name, scoped to docs the agent itself created (drive.file scope)")

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
    mcp.register(list_drive_files, name="list_google_drive_files", description="List files (PDFs, images, etc) the agent itself created in Google Drive — drive.file scope means the user's other files are not visible")
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
    mcp.register(search_zynd_personas, name="search_zynd_personas", description="Search the Zynd Network for people, personas, or agents. Use this FIRST when looking for someone.")
    mcp.register(get_persona_profile, name="get_persona_profile", description="Get the full profile of a specific persona (social links, capabilities, description)")
    mcp.register(list_my_connections, name="list_my_connections", description="List all the user's existing network connections and pending requests")
    mcp.register(request_connection, name="request_connection", description="Send a connection request to another persona on the Zynd Network")
    mcp.register(check_connection_status, name="check_connection_status", description="Check if the user is connected to a specific persona")
    mcp.register(message_zynd_agent, name="message_zynd_agent", description="Send a message to another persona's agent on the Zynd Network")
    mcp.register(read_agent_channel, name="read_agent_channel", description="Read recent agent-channel messages on a DM thread. Use to check what was said across turns, verify replies arrived, or reconstruct context. Never reads the human Conversation tab.")

    # ── Zynd Network service-discovery tools ───────────────────────
    # Three-step flow when no built-in tool covers the user's ask:
    # search → get_card (to learn the I/O schema and the real URL) → call.
    mcp.register(search_zynd_services, name="search_zynd_services", description="Discover off-network capabilities (translation, file/format conversion like pdf→text or xml→json, currency conversion, summarization, niche lookups) published as services on the Zynd Network. Use this when, and ONLY when, no built-in tool covers the principal's ask. Returns ranked entity_ids — pass the best to get_zynd_service_card next. Do NOT call this for tasks an LLM can answer from general knowledge.")
    mcp.register(get_zynd_service_card, name="get_zynd_service_card", description="REQUIRED step between search_zynd_services and call_zynd_service. Returns the service's input_schema (decides what fields to pass), output_schema, real callable URL, and live status. Read input_schema BEFORE calling: task-specific fields (target_language, amount, etc.) → pass them in `data=`; single content/text field → use `text=`. Never skip this — the search result's service_endpoint is internal and not callable.")
    mcp.register(call_zynd_service, name="call_zynd_service", description="Invoke a Zynd service via A2A JSON-RPC. Shape the payload from input_schema: pass `data={...}` with structured fields when the schema declares them, or `text=...` for free-text-only schemas. You may pass both. Prefer `structured_output` over `reply_text` when present. On status=unreachable/not_found, try the next search result; do NOT retry the same id. Lead replies with the answer, not 'I called a service'.")

    # ── Scheduling / meeting tools ─────────────────────────────────
    mcp.register(propose_meeting, name="propose_meeting", description="Formalise a negotiated meeting as a ticket on a DM thread. Only call AFTER negotiating a time and getting your principal's explicit confirmation.")
    mcp.register(propose_group_meeting, name="propose_group_meeting", description="Propose a meeting in a group room. The principal sees an approval card; on accept, the calendar event is created with every other group member as an attendee and a system message is posted to the group chat.")
    mcp.register(respond_to_meeting, name="respond_to_meeting", description="Accept, counter, decline, or cancel an existing meeting ticket.")
    mcp.register(list_pending_meetings, name="list_pending_meetings", description="List the principal's open meeting tickets, split by who needs to act next.")

    # ── Brief tools (principal-private) ────────────────────────────
    # These read/write the user's Brief Google Doc. Auto-init the doc
    # on first append/replace. Never exposed to foreign agents.
    mcp.register(read_my_brief, name="read_my_brief", description="Read the principal's Brief — the long-form context doc this persona uses to know its principal. Returns plain text + Google Doc URL. Use this whenever you need durable context about the user (preferences, role, ongoing projects).")
    mcp.register(append_to_my_brief, name="append_to_my_brief", description="Append a line to the principal's Brief Google Doc. Use this when the user tells you something durable about themselves that you should remember across conversations. Creates the brief lazily if it doesn't exist yet.")
    mcp.register(replace_my_brief, name="replace_my_brief", description="Replace the entire body of the principal's Brief Google Doc. Use only when the user explicitly asks to rewrite their brief — prefer append_to_my_brief for additions.")
    mcp.register(clear_my_brief, name="clear_my_brief", description="Empty the principal's Brief Google Doc. Use only when the user explicitly asks to clear their brief.")
    mcp.register(add_todo, name="add_todo", description="Add an actionable todo to the principal's todo list. PREFER this tool over append_to_my_brief whenever the user explicitly asks to track a task — phrases like 'add a todo', 'remind me to', 'put X on my list', 'add this to my todos'. The item shows up immediately on the dashboard's Todos tab (no 5-minute extractor wait). For general profile facts ('I work at X', 'I prefer afternoons'), use append_to_my_brief instead.")

    # ── Default utility tools ──────────────────────
    mcp.register_default(names=["internet_search", "webpage_scrape", "get_current_time", "calculate"])

    return mcp

mcp_server = create_mcp_server()
