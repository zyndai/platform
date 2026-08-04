"""
A2A Network MCP Tools — persona-facing tools for network introductions,
smart scheduling, and cross-instance coordination.
"""

from __future__ import annotations


async def find_best_intro_for_me(
    user_id: str,
    topic: str,
    top_k: int = 5,
) -> str:
    """Find the best person on the Zynd network to connect with about a topic.

    Use when the user asks:
      - "Who should I talk to about fundraising?"
      - "Find me someone who knows about AI agents"
      - "Who on the network can help with hiring?"
      - "Introduce me to people in biotech"

    Searches the network, checks connections, finds mutual contacts,
    and ranks results by relevance + trust + shared context.

    Args:
        topic: What the user wants to connect about.
        top_k: Number of recommendations to return (default 5).
    """
    from agent.network_intros import find_best_introduction

    result = await find_best_introduction(
        user_id=user_id,
        topic=topic,
        top_k=top_k,
    )

    if not result.get("matches"):
        return (
            f"I searched the Zynd network but didn't find anyone matching '{topic}'. "
            "Try different keywords or broaden the search."
        )

    lines = [f"## Best matches for '{topic}'", ""]

    for i, match in enumerate(result["matches"], 1):
        name = match.get("name", "Unknown")
        entity_id = match.get("entity_id", "")
        score = match.get("score", 0)
        conn = match.get("connection_status", "none")

        conn_label = {
            "accepted": "✅ Connected",
            "pending": "⏳ Pending",
            "blocked": "🚫 Blocked",
            "revoked": "🚫 Revoked",
            "none": "👋 New",
        }.get(conn, conn)

        lines.append(f"**{i}. {name}** — {conn_label} (score: {score:.2f})")

        # Capabilities.
        capabilities = match.get("capabilities", [])
        if capabilities:
            lines.append(f"   Capabilities: {', '.join(capabilities[:3])}")

        # Mutual connections.
        mutual = match.get("mutual_context", [])
        if mutual:
            lines.append(f"   {len(mutual)} mutual connection(s)")

        # Description.
        desc = match.get("description", "")
        if desc:
            lines.append(f"   {desc[:150]}")

        lines.append("")

    # Recommended.
    rec = result.get("recommended")
    if rec:
        lines.append(f"**Top recommendation: {rec.get('name')}**")
        lines.append(rec.get("reason", ""))
        lines.append("")

    # Intro draft.
    draft = result.get("intro_draft")
    if draft:
        lines.append(f"*{draft}*")

    return "\n".join(lines)


async def check_network_overlap(
    user_id: str,
    target_name_or_id: str,
) -> str:
    """Check what two people have in common on the Zynd network.

    Use when the user asks:
      - "What do I have in common with Alice?"
      - "Do we share any connections?"
      - "What would be a good icebreaker?"

    Looks up shared interests, mutual connections, and common topics.

    Args:
        target_name_or_id: A name or agent_id to check overlap with.
    """
    from agent.network_intros import get_network_overlap

    overlap = await get_network_overlap(
        user_id=user_id,
        target_agent_id=target_name_or_id,
    )

    conn = overlap.get("connection_status", "unknown")
    conn_labels = {
        "accepted": "✅ You're connected",
        "pending": "⏳ Connection pending",
        "blocked": "🚫 Blocked",
        "none": "👋 Not connected yet",
    }

    lines = ["## Network Overlap", ""]
    lines.append(f"Status: {conn_labels.get(conn, conn)}")

    known = overlap.get("known_context", [])
    if known:
        lines.append(f"\nYou've mentioned them before: *{known[0][:120]}*")

    interests = overlap.get("shared_interests", [])
    if interests:
        lines.append(f"\nShared interests: {', '.join(interests[:5])}")

    connections = overlap.get("shared_connections", [])
    if connections:
        lines.append(f"\n{len(connections)} mutual connection(s)")

    icebreaker = overlap.get("suggested_icebreaker")
    if icebreaker:
        lines.append(f"\n💬 *{icebreaker}*")

    if not (known or interests or connections):
        lines.append("\nNo obvious common ground found yet.")

    return "\n".join(lines)


async def smart_group_schedule(
    user_id: str,
    group_id: str,
    start_date: str,
    end_date: str,
    duration_minutes: int = 30,
) -> str:
    """Find the best meeting time for a group using everyone's calendars.

    Use when the user asks:
      - "Find a time this week when we're all free"
      - "Schedule a 30-min standup for the team"
      - "What's the best slot for our group meeting?"

    Queries each member's Google Calendar (if connected) and ranks
    available slots by how many people can attend.

    Args:
        group_id: The group to schedule for.
        start_date: Start of the search window (ISO date: "2026-08-05").
        end_date: End of the search window.
        duration_minutes: How long the meeting should be (default 30).
    """
    import config as _c
    sb = _c.get_supabase()

    # Get group members.
    try:
        members = (
            sb.table("persona_group_members")
            .select("user_id")
            .eq("group_id", group_id)
            .execute()
        )
        if not members.data:
            return "This group has no members."

        # Enrich with persona info.
        participant_ids = [m["user_id"] for m in members.data]
        personas = (
            sb.table("persona_agents")
            .select("user_id, name, agent_id")
            .in_("user_id", participant_ids)
            .eq("active", True)
            .execute()
        )
        participants = personas.data or []

    except Exception as e:
        return f"Failed to fetch group members: {e}"

    from agent.smart_scheduling import find_best_meeting_slots

    result = await find_best_meeting_slots(
        group_id=group_id,
        start_date=start_date,
        end_date=end_date,
        duration_minutes=duration_minutes,
        participants=participants,
    )

    lines = [f"## Group Availability: {start_date} to {end_date}", ""]

    # Unavailable members.
    unavailable = result.get("unavailable", [])
    if unavailable:
        lines.append("⚠️ No calendar access:")
        for u in unavailable:
            lines.append(f"   - {u.get('name', 'Unknown')} ({u.get('reason', '?')})")
        lines.append("")

    # Best slots.
    slots = result.get("slots", [])
    if not slots:
        lines.append(
            f"No common slots found with {result.get('participants_with_calendar', 0)}/"
            f"{result.get('total_participants', 0)} calendars. Try a wider date range."
        )
        return "\n".join(lines)

    lines.append(
        f"Found {len(slots)} slots ({result['participants_with_calendar']}/"
        f"{result['total_participants']} calendars queried):"
    )
    lines.append("")

    for i, slot in enumerate(slots[:8]):
        start = slot.get("start", "?").replace("T", " ").replace("Z", "")
        score = slot.get("score", 0)
        avail = f"{slot.get('available_count', 0)}/{slot.get('total_count', 0)}"
        lines.append(f"{i+1}. {start} — {avail} available (score: {score:.2f})")

    # Recommended.
    rec = result.get("recommended")
    if rec:
        rec_start = rec.get("start", "").replace("T", " ").replace("Z", "")
        lines.append(f"\n**Best pick: {rec_start}** — click to propose this time.")

    return "\n".join(lines)
