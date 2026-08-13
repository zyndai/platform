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
from mcp.tools.linkedin import post_to_linkedin, send_linkedin_dm, read_linkedin_dms, read_linkedin_profile, search_linkedin_people

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
    search_zynd_network,
    search_zynd_personas,
    get_persona_profile,
    list_my_connections,
    request_connection,
    check_connection_status,
    message_zynd_agent,
    call_zynd_agent,
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

# ── Import Publish Page Tools ──
# Principal-private; never added to any external allowlist.
from mcp.tools.publish_page import publish_page, update_page, list_my_pages

# ── Import Brief Tools ──
# Principal-private; never added to any external allowlist.
from mcp.tools.brief import (
    read_my_brief,
    append_to_my_brief,
    replace_my_brief,
    clear_my_brief,
    add_todo,
)

# ── Import Memory Tools ──
# Principal-private; querying/forgetting memory facts.
from mcp.tools.memory import (
    what_do_you_know_about_me,
    remember_this,
    remember_this_structured,
    forget_this,
)

# ── Import Digital Twin Tools ──
# Principal-private; style cloning, knowledge Q&A, delegation.
from mcp.tools.twin import (
    answer_like_me,
    delegate_to_my_persona,
    what_do_i_really_know_about,
    refresh_my_style,
)

# ── Import A2A Network Tools ──
# Principal-private; network intros, smart scheduling, overlap checks.
from mcp.tools.a2a_network import (
    find_best_intro_for_me,
    check_network_overlap,
    smart_group_schedule,
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
    mcp.register(read_linkedin_profile, name="read_linkedin_profile", description="Read the principal's scraped LinkedIn profile — headline, experience, education, skills, and recent posts. Use this when the principal asks about their own LinkedIn background or work history.")
    mcp.register(search_linkedin_people, name="search_linkedin_people", description="Search LinkedIn itself for people by role/topic/keyword (e.g. 'AI founders'). Real, metered LinkedIn scrape — separate from search_zynd_personas, which only covers people with a Zynd persona. Use when asked to find people 'on LinkedIn', or automatically as the next step when a Zynd Network people search comes back thin — narrate the broaden, don't ask permission first.")

    # ── Google Calendar tools ────────────────────────────────────────
    mcp.register(create_event, name="create_calendar_event", description="Create an event on Google Calendar. Pass `attendees` (a list of email addresses) to invite guests — Google emails them the invite automatically. Checks for conflicts with existing events first: if the time overlaps something already on the calendar, it returns {conflict: true, conflicting_events, suggested_times} and does NOT create the event — present the conflict and suggested_times to the principal instead of retrying blindly. Only pass force=true to double-book anyway, and only when the principal explicitly asked for that after seeing the conflict.")
    mcp.register(list_events, name="list_calendar_events", description="List Google Calendar events. Pass `time_min`/`time_max` (ISO 8601) to check a specific window — e.g. before proposing a time, to see what's already booked — instead of relying on the default 'next N upcoming events'.")
    mcp.register(delete_event, name="delete_calendar_event", description="Delete a Google Calendar event")

    # ── Google Docs tools ──────────────────────────────────────────
    mcp.register(create_document, name="create_google_doc", description="Create a new Google Document")
    mcp.register(append_to_document, name="append_to_google_doc", description="Append text to a Google Document")
    mcp.register(read_document, name="read_google_doc", description="Read the entire content of a Google Document")
    mcp.register(list_google_docs, name="list_google_docs", description="List the most recently modified Google Documents the agent itself created (drive.file scope — the user's other docs are not visible)")
    mcp.register(search_google_docs, name="search_google_docs", description="Find Google Documents by name, scoped to docs the agent itself created (drive.file scope)")

    # ── Google Gmail tools ──────────────────────────────────────────
    mcp.register(search_emails, name="search_gmail_emails", description="Search Gmail for messages matching a query (e.g. from:someone)")
    mcp.register(get_email_details, name="get_gmail_email_details", description="Get the full body and headers of a specific email, including `thread_id` and `message_id_header` — pass both to `send_gmail_email` when replying so the reply lands in this exact thread instead of a new/wrong one.")
    mcp.register(send_email, name="send_gmail_email", description="Send an email through Gmail. When REPLYING to an existing email (not composing a new one), first call `get_gmail_email_details` on it and pass its `thread_id` and `message_id_header` here as `thread_id`/`in_reply_to_message_id` — otherwise Gmail has to guess the thread from the subject line alone and can misfile the reply into the wrong conversation.")
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
    mcp.register(search_zynd_network, name="search_zynd_network", description="Search the Zynd Network for ANY callable entity — personas, services, and standalone agents. Use this FIRST when the user asks to find an agent / service / persona / 'something that can do X' without specifying which kind. Each result has a `kind` field that decides how to call it: 'persona' → needs request_connection + accept, then message_zynd_agent; 'service' (zns:svc:…, fast/stateless) → get_zynd_service_card → call_zynd_service (synchronous); 'agent' or a domain category (standalone, may be long-running) → call_zynd_agent (signed + asynchronous, no connection needed). Pass kind='persona' or kind='service' to narrow when you know the target type.")
    mcp.register(search_zynd_personas, name="search_zynd_personas", description="Persona-only search (humans' AI personas). Prefer search_zynd_network unless the user explicitly asked for a person.")
    mcp.register(get_persona_profile, name="get_persona_profile", description="Get the full profile of a specific persona (social links, capabilities, description)")
    mcp.register(list_my_connections, name="list_my_connections", description="List all the user's existing network connections and pending requests")
    mcp.register(request_connection, name="request_connection", description="Send a connection request to another persona on the Zynd Network")
    mcp.register(check_connection_status, name="check_connection_status", description="Check if the user is connected to a specific persona")
    mcp.register(message_zynd_agent, name="message_zynd_agent", description="Send a message to another persona's agent on the Zynd Network")
    mcp.register(call_zynd_agent, name="call_zynd_agent", description="Call a standalone Zynd Network AGENT (a search_zynd_network result whose kind is 'agent' or a domain category — NOT a zns:svc: service and NOT a persona). Signs the request with the principal's keypair (services don't), so auth-requiring agents accept it, and dispatches ASYNCHRONOUSLY: status='dispatched' means the agent is running and its reply will arrive in the chat later — tell the user and do NOT wait/re-poll. If the agent answered inline (no push support) you get status='success'/'bad_request'/etc. with reply_text/structured_output. No connection request needed.")
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

    # ── Publish Page tools (principal-private) ─────────────────────
    # Create shareable HTML / Markdown pages and list existing pages.
    # Never exposed to foreign agents.
    mcp.register(publish_page, name="publish_page", description="Publish a shareable HTML or Markdown page for the principal. Returns a public URL like https://<host>/pages/<slug> that they can share with friends. Use when the principal asks you to turn content into a web page, save HTML/Markdown, or create a shareable link.")
    mcp.register(update_page, name="update_page", description="Edit/update an existing shareable page the principal published. Requires the page slug (the last part of the /pages/<slug> URL). Use when the principal asks to change, edit, or update a page they already made. Only pass the fields that need to change.")
    mcp.register(list_my_pages, name="list_my_pages", description="List the shareable pages the principal has already published. Use when they ask to see their pages, e.g. 'show my pages' or 'what pages have I made'.")

    # ── Brief tools (principal-private) ────────────────────────────
    # These read/write the user's Brief (a plain-text field on the
    # persona row). Never exposed to foreign agents.
    mcp.register(read_my_brief, name="read_my_brief", description="Read the principal's Brief — the long-form context this persona uses to know its principal. Returns the plain-text body. Use this whenever you need durable context about the user (preferences, role, ongoing projects).")
    mcp.register(append_to_my_brief, name="append_to_my_brief", description="Append a line to the principal's Brief. Use this when the user tells you something durable about themselves that you should remember across conversations.")
    mcp.register(replace_my_brief, name="replace_my_brief", description="Replace the entire body of the principal's Brief. Use only when the user explicitly asks to rewrite their brief — prefer append_to_my_brief for additions.")
    mcp.register(clear_my_brief, name="clear_my_brief", description="Empty the principal's Brief. Use only when the user explicitly asks to clear their brief.")
    mcp.register(add_todo, name="add_todo", description="Add an actionable todo to the principal's todo list. PREFER this tool over append_to_my_brief whenever the user explicitly asks to track a task — phrases like 'add a todo', 'remind me to', 'put X on my list', 'add this to my todos'. The item shows up immediately on the dashboard's Todos tab (no 5-minute extractor wait). For general profile facts ('I work at X', 'I prefer afternoons'), use append_to_my_brief instead.")

    # ── Default utility tools ──────────────────────
    mcp.register_default(names=["internet_search", "webpage_scrape", "get_current_time", "calculate"])

    # ── Memory tools (principal-private) ────────────────────────────
    # These query the ZYND memory layer for long-term recall.
    mcp.register(what_do_you_know_about_me, name="what_do_you_know_about_me", description="Query the persona's long-term memory about the principal. Use when the user asks what you remember about them, what they're working on, their goals, preferences, past conversations, or anything about their life. Provide a topic keyword for filtered results (e.g. 'startup', 'health', 'travel').")
    mcp.register(remember_this, name="remember_this", description="Persist a single fact the user explicitly wants remembered. Use when the user says 'remember that...', 'make a note...', or 'don't forget...'. The fact should be a clear statement (e.g. 'The principal is allergic to peanuts').")
    mcp.register(remember_this_structured, name="remember_this_structured", description="Write a single structured PRIVATE memory fact as an explicit (predicate, value) declaration. Use for crisp durable facts that map to a known predicate — e.g. 'I'm building an AI startup' → predicate='is_building', value='an AI startup'. Predicates include is_building, is_working_on, is_learning, has_expertise_in, intends_to, fears, believes, values, is_located_in, has_collaborator, and more. Prefer remember_this (free text) when the fact doesn't map cleanly to a predicate.")
    mcp.register(forget_this, name="forget_this", description="Remove or decay a fact the user wants forgotten. Use when the user says 'forget that...', 'I don't actually...', or asks to remove something from memory.")

    # ── Digital Twin tools (principal-private) ──────────────────────
    # These let the persona answer personal questions, delegate tasks,
    # and match the principal's communication style.
    mcp.register(answer_like_me, name="answer_like_me", description="Answer a personal question using the principal's memory graph and communication style. Use when the user asks about themselves, their work, opinions, or knowledge — anything that requires synthesizing facts from past conversations. More powerful than what_do_you_know_about_me because it uses the LLM to craft a natural answer.")
    mcp.register(delegate_to_my_persona, name="delegate_to_my_persona", description="Delegate a multi-step task for the persona to complete offline. Use when the user wants something that needs research, drafting, or delivery — like 'brief Sarah on Q3 numbers', 'draft an investor update', or 'compile competitor research'. The persona gathers context from memory, drafts in the user's style, and delivers to the target.")
    mcp.register(what_do_i_really_know_about, name="what_do_i_really_know_about", description="Deep-dive into the memory graph on a specific topic. Groups facts by category, shows confidence bars, and flags contradictions. Use when the user asks for a comprehensive picture — 'tell me everything about X'.")
    mcp.register(refresh_my_style, name="refresh_my_style", description="Re-analyze the principal's recent conversation history and update their communication style profile. Use when the persona doesn't sound like the principal, or after many conversations to keep the style current.")

    # ── A2A Network tools (principal-private) ─────────────────────
    mcp.register(find_best_intro_for_me, name="find_best_intro_for_me", description="Find the best person on the Zynd network to connect with about a topic. Searches personas, checks existing connections, finds mutual contacts, and ranks by relevance + trust. Use when the user asks 'who should I talk to about X?'")
    mcp.register(check_network_overlap, name="check_network_overlap", description="Check what the principal has in common with another person on the network — shared interests, mutual connections, and suggested icebreakers. Use when asked 'what do I have in common with X?'")
    mcp.register(smart_group_schedule, name="smart_group_schedule", description="Find the best meeting time for a group using everyone's Google Calendars. Queries each member's availability and ranks slots by how many people can attend. Use when asked 'find a time we're all free' or 'schedule a group meeting'.")

    return mcp

mcp_server = create_mcp_server()
