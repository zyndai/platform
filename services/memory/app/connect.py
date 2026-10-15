"""Public MCP setup entry point; authentication happens in the client's OAuth flow."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.docs import install_guide

router = APIRouter(tags=["connect"])


@router.get("/connect", response_class=HTMLResponse)
async def connect_form() -> HTMLResponse:
    return await install_guide()


@router.post("/connect", response_class=HTMLResponse)
async def connect() -> HTMLResponse:
    return HTMLResponse(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<title>Connect setup moved</title></head><body>'
        '<h1>Password signup here has been retired</h1>'
        '<p>No account or token was created. Use the '
        '<a href="/install">URL-only MCP OAuth setup guide</a> instead. '
        'You need an existing Zynd account; sign in and approve access in the browser '
        'when your MCP client starts authentication.</p></body></html>',
        headers={"Cache-Control": "no-store"},
        status_code=410,
    )
