"""Session lifecycle endpoints.

A session id IS the LangGraph ``thread_id`` — creating a session reserves the
thread the checkpointer will persist a conversation under. These endpoints back
the history sidebar (list + replay) and the "new chat" action.
"""

from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

from backend.db.queries import (
    create_session,
    get_messages,
    get_session,
    list_sessions,
)

router = APIRouter(prefix="/api", tags=["sessions"])


def _parse_events(events_json: str | None) -> list:
    """Decode a stored ``events_json`` blob back into a list for replay.

    Stored messages keep the structured SSE events (route / product_cards /
    cart_update / confirm_request) that accompanied them so the frontend can
    rebuild the rich turn without re-running the graph. Malformed/empty blobs
    degrade to an empty list rather than failing the whole replay.
    """

    if not events_json:
        return []
    try:
        decoded = json.loads(events_json)
    except (json.JSONDecodeError, TypeError):
        return []
    return decoded if isinstance(decoded, list) else []


@router.post("/sessions")
async def post_session(request: Request) -> dict:
    """Create a new session (= new checkpoint thread) and return its id."""

    settings = request.app.state.settings
    session_id = uuid4().hex
    await create_session(session_id, settings.shopify_store_domain)
    return {"session_id": session_id}


@router.get("/sessions")
async def get_sessions() -> dict:
    """List sessions newest-first, each with a truncated first-message preview."""

    rows = await list_sessions()
    sessions = [
        {
            "session_id": row["id"],
            "store_domain": row.get("store_domain"),
            "cart_id": row.get("cart_id"),
            "created_at": str(row.get("created_at")) if row.get("created_at") else None,
            "last_active": str(row.get("last_active")) if row.get("last_active") else None,
            "preview": row.get("preview") or "",
        }
        for row in rows
    ]
    return {"sessions": sessions}


@router.get("/sessions/{session_id}")
async def get_session_detail(session_id: str) -> dict:
    """Return a session's messages (with replay events) or 404 if unknown."""

    session = await get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    rows = await get_messages(session_id)
    messages = [
        {
            "id": row["id"],
            "role": row["role"],
            "content": row["content"],
            "events": _parse_events(row.get("events_json")),
            "created_at": str(row.get("created_at")) if row.get("created_at") else None,
        }
        for row in rows
    ]
    return {
        "session_id": session_id,
        "cart_id": session.get("cart_id"),
        "messages": messages,
    }
