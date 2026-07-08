
import asyncio
from typing import Any

from app.services import meetings as meetings_svc


async def propose_meeting(user_id: str, thread_id: str, title: str, start_time: str,
                          end_time: str, location: str = "", description: str = "") -> dict:
    try:
        row = await meetings_svc.create_proposal(
            thread_id=thread_id,
            actor_user_id=user_id,
            payload={
                "title": title, "start_time": start_time, "end_time": end_time,
                "location": location, "description": description,
            },
        )
    except meetings_svc.MeetingError as e:
        return {"error": str(e)}
    return {
        "status": "success", "task_id": row["id"], "thread_id": row["thread_id"],
        "meeting_status": row["status"], "payload": row["payload"],
        "message": f"Meeting proposal '{title}' sent. Awaiting the other side's confirmation.",
    }


async def respond_to_meeting(user_id: str, task_id: str, action: str,
                              title: str = "", start_time: str = "", end_time: str = "",
                              location: str = "", description: str = "") -> dict:
    edits: dict[str, Any] = {}
    if action == "counter":
        if title:
            edits["title"] = title
        if start_time:
            edits["start_time"] = start_time
        if end_time:
            edits["end_time"] = end_time
        if location:
            edits["location"] = location
        if description:
            edits["description"] = description
    try:
        row = await meetings_svc.respond_to_proposal(
            task_id=task_id, actor_user_id=user_id, action=action,
            edits=edits or None,
        )
    except meetings_svc.MeetingError as e:
        return {"error": str(e)}
    return {
        "status": "success", "task_id": row["id"], "thread_id": row["thread_id"],
        "meeting_status": row["status"], "payload": row["payload"],
        "message": f"Meeting {row['status']}.",
    }


async def list_pending_meetings(user_id: str) -> dict:
    result = meetings_svc.list_pending_for_user(user_id)
    return {
        "status": "success",
        "awaiting_me_count": len(result["awaiting_me"]),
        "awaiting_them_count": len(result["awaiting_them"]),
        "awaiting_me": result["awaiting_me"],
        "awaiting_them": result["awaiting_them"],
    }


async def propose_group_meeting(user_id: str, group_id: str, title: str, start_time: str,
                                 end_time: str, location: str = "", description: str = "",
                                 time_zone: str = "") -> dict:
    return {"error": "Group meeting scheduling is not supported in memory-layer MCP."}
