
import asyncio

import httpx

from app.services.token_store import get_tokens

NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"
DEFAULT_TIMEOUT = 12.0


def _notion_request(method: str, path: str, user_id: str, payload: dict = None) -> dict:
    tokens = get_tokens(user_id=user_id, provider="notion")
    if not tokens:
        raise ValueError("Notion not connected. Please connect your Notion account.")

    headers = {
        "Authorization": f"Bearer {tokens['access_token']}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json",
    }
    url = f"{NOTION_BASE_URL}/{path.lstrip('/')}"
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.request(method, url, headers=headers, json=payload)
            if resp.status_code == 429:
                return {"success": False, "error": "Rate limited by Notion. Please try again in a moment."}
            resp.raise_for_status()
            return {"success": True, "data": resp.json()}
    except httpx.HTTPStatusError:
        return {"success": False, "error": f"Notion API error"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def build_notion_properties(data: dict, schema: dict = None) -> dict:
    props = {}
    for key, val in data.items():
        prop_type = "rich_text"
        if schema and key in schema:
            prop_type = schema[key].get("type", "rich_text")
        else:
            if isinstance(val, bool):
                prop_type = "checkbox"
            elif key.lower() in ["name", "title"]:
                prop_type = "title"
            elif key.lower() in ["date", "due date", "deadline"]:
                prop_type = "date"
            elif isinstance(val, list):
                prop_type = "multi_select"
        if prop_type == "title":
            props[key] = {"title": [{"type": "text", "text": {"content": str(val)}}]}
        elif prop_type == "rich_text":
            props[key] = {"rich_text": [{"type": "text", "text": {"content": str(val)}}]}
        elif prop_type == "select":
            props[key] = {"select": {"name": str(val)}}
        elif prop_type == "multi_select":
            items = val if isinstance(val, list) else [str(val)]
            props[key] = {"multi_select": [{"name": str(i)} for i in items]}
        elif prop_type == "checkbox":
            props[key] = {"checkbox": bool(val)}
        elif prop_type == "date":
            props[key] = {"date": {"start": val}}
        elif prop_type == "number":
            try:
                props[key] = {"number": float(val)}
            except (ValueError, TypeError):
                pass
    return props


def format_notion_blocks(blocks: list[dict]) -> list[dict]:
    formatted = []
    for b in blocks:
        b_type = b.get("type", "paragraph")
        text = b.get("text", "")
        block = {
            "object": "block",
            "type": b_type,
            b_type: {"rich_text": [{"type": "text", "text": {"content": text}}]},
        }
        if b_type == "to_do":
            block["to_do"]["checked"] = b.get("checked", False)
        elif b_type == "callout":
            block["callout"]["icon"] = {"emoji": b.get("emoji", "\U0001f4a1")}
        if "children" in b:
            block[b_type]["children"] = format_notion_blocks(b["children"])
        formatted.append(block)
    return formatted


async def search_notion(user_id: str, query: str = "", filter_type: str = None) -> dict:
    results = []
    has_more = True
    start_cursor = None
    while has_more and len(results) < 100:
        payload = {"query": query, "page_size": 50}
        if start_cursor:
            payload["start_cursor"] = start_cursor
        if filter_type:
            payload["filter"] = {"value": filter_type, "property": "object"}
        res = await asyncio.to_thread(_notion_request, "POST", "search", user_id, payload)
        if not res["success"]:
            return res
        data = res["data"]
        results.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor")

    formatted = []
    for item in results:
        title = "Untitled"
        obj_type = item["object"]
        if obj_type == "page":
            props = item.get("properties", {})
            for p_val in props.values():
                if p_val.get("type") == "title" and p_val.get("title"):
                    title = "".join([t.get("plain_text", "") for t in p_val["title"]])
                    break
        elif obj_type == "database":
            title = "".join([t.get("plain_text", "") for t in item.get("title", [])])
        formatted.append({"id": item["id"], "type": obj_type, "name": title, "url": item.get("url")})
    return {"success": True, "results": formatted}


async def get_notion_database(user_id: str, database_id: str) -> dict:
    res = _notion_request("GET", f"databases/{database_id}", user_id)
    if not res["success"]:
        return res
    data = res["data"]
    return {
        "success": True,
        "id": data["id"],
        "title": "".join([t.get("plain_text", "") for t in data.get("title", [])]),
        "properties": {k: {"type": v["type"], "id": v["id"]} for k, v in data.get("properties", {}).items()},
    }


async def query_notion_database(user_id: str, database_id: str, filter_data: dict = None, sorts: list = None) -> dict:
    payload = {"page_size": 50}
    if filter_data:
        payload["filter"] = filter_data
    if sorts:
        payload["sorts"] = sorts
    res = await asyncio.to_thread(_notion_request, "POST", f"databases/{database_id}/query", user_id, payload)
    if not res["success"]:
        return res
    return {"success": True, "results": res["data"].get("results", [])}


async def create_notion_page(user_id: str, parent_id: str, properties: dict = None, title: str = None, content: list = None) -> dict:
    is_db = False
    schema = None
    properties = properties or {}
    if title:
        properties["title"] = title
    db_res = await get_notion_database(user_id, parent_id)
    if db_res["success"]:
        is_db = True
        schema = db_res["properties"]
    notion_props = build_notion_properties(properties, schema)
    payload = {
        "parent": {"database_id": parent_id} if is_db else {"page_id": parent_id},
        "properties": notion_props,
    }
    if content:
        payload["children"] = content
    res = await asyncio.to_thread(_notion_request, "POST", "pages", user_id, payload)
    if not res["success"] and not is_db:
        payload["parent"] = {"page_id": parent_id}
        res = await asyncio.to_thread(_notion_request, "POST", "pages", user_id, payload)
    return res


async def update_notion_page(user_id: str, page_id: str, properties: dict = None, title: str = None) -> dict:
    properties = properties or {}
    if title:
        properties["title"] = title
    res_get = _notion_request("GET", f"pages/{page_id}", user_id)
    schema = None
    if res_get["success"]:
        parent = res_get["data"].get("parent", {})
        if parent.get("type") == "database_id":
            db_id = parent["database_id"]
            db_res = await get_notion_database(user_id, db_id)
            if db_res["success"]:
                schema = db_res["properties"]
    notion_props = build_notion_properties(properties, schema)
    return _notion_request("PATCH", f"pages/{page_id}", user_id, {"properties": notion_props})


async def get_notion_page_content(user_id: str, page_id: str) -> dict:
    blocks = []
    has_more = True
    start_cursor = None
    while has_more:
        path = f"blocks/{page_id}/children?page_size=100"
        if start_cursor:
            path += f"&start_cursor={start_cursor}"
        res = await asyncio.to_thread(_notion_request, "GET", path, user_id)
        if not res["success"]:
            return res
        data = res["data"]
        blocks.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor")
    return {"success": True, "blocks": blocks}


async def create_notion_database(user_id: str, parent_page_id: str, title: str, schema: dict) -> dict:
    notion_props = {}
    if "properties" in schema and isinstance(schema["properties"], dict):
        schema = schema["properties"]
    for name, p_type in schema.items():
        if isinstance(p_type, str):
            notion_props[name] = {p_type: {}}
        elif isinstance(p_type, dict):
            if "type" in p_type:
                notion_props[name] = {p_type["type"]: {}}
            else:
                notion_props[name] = p_type
        else:
            notion_props[name] = {"rich_text": {}}
    if not any("title" in v for v in notion_props.values()):
        notion_props["Name"] = {"title": {}}
    payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": notion_props,
    }
    return await asyncio.to_thread(_notion_request, "POST", "databases", user_id, payload)


async def append_notion_blocks(user_id: str, page_id: str, blocks: list[dict]) -> dict:
    formatted = format_notion_blocks(blocks)
    return await asyncio.to_thread(_notion_request, "PATCH", f"blocks/{page_id}/children", user_id, {"children": formatted})
