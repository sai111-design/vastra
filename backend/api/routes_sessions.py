"""Session lifecycle endpoints.

A session id IS the LangGraph ``thread_id`` — creating a session reserves the
thread the checkpointer will persist a conversation under. These endpoints back
the history sidebar (list + replay) and the "new chat" action.
"""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.db.queries import (
    create_session,
    get_messages,
    get_session,
    list_sessions,
    upsert_buyer_profile,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["sessions"])


# ---------------------------------------------------------------------------
# Onboarding quiz → buyer profile mapping (E4)
# ---------------------------------------------------------------------------
# Each vibe answer expands to a small style_tags list the Stylist prompt reads
# silently. Keeping the lists tight (3 tags) avoids over-constraining searches
# while still meaningfully shaping picks from turn one.
_VIBE_TO_STYLE_TAGS: dict[str, list[str]] = {
    "minimal": ["minimal", "clean", "neutral"],
    "streetwear": ["streetwear", "oversized", "graphic"],
    "ethnic": ["ethnic", "fusion", "traditional"],
    "casual": ["casual", "everyday", "comfort"],
}

# Inclusive lower bound, soft upper bound. The top "above_1500" bucket caps at
# 9999 so the Stylist still treats it as an explicit ceiling.
_BUDGET_TO_RANGE: dict[str, tuple[int, int]] = {
    "under_500": (0, 500),
    "500_1500": (500, 1500),
    "above_1500": (1500, 9999),
}


class InitialProfile(BaseModel):
    """Buyer-quiz answers used to seed the profile before the first turn."""

    vibe: str | None = None
    budget: str | None = None
    # Multi-select on the quiz; "surprise_me" deselects the others on the
    # client, so this list is either ["surprise_me"] or a non-surprise subset.
    categories: list[str] = []


class CreateSessionRequest(BaseModel):
    initial_profile: InitialProfile | None = None


def _profile_seed(quiz: InitialProfile) -> dict | None:
    """Translate quiz answers into the upsert_buyer_profile arg shape.

    Returns None when the buyer skipped every step (nothing to seed), so the
    caller can keep a clean "no profile row" state and let the Preference
    Extractor populate things naturally as the conversation unfolds.
    """

    style_tags = _VIBE_TO_STYLE_TAGS.get((quiz.vibe or "").strip().lower(), [])

    budget_min: int | None = None
    budget_max: int | None = None
    bucket = (quiz.budget or "").strip().lower()
    if bucket in _BUDGET_TO_RANGE:
        budget_min, budget_max = _BUDGET_TO_RANGE[bucket]

    # "surprise_me" intentionally leaves last_category empty so the Stylist
    # picks freely on turn one; the auto-sent message carries the intent.
    cats = [c for c in (quiz.categories or []) if c and c != "surprise_me"]
    last_category = cats[0] if cats else None

    if not (style_tags or budget_min is not None or budget_max is not None or last_category):
        return None

    return {
        "sizes_json": json.dumps({}),
        "budget_min": budget_min,
        "budget_max": budget_max,
        "style_tags": json.dumps(style_tags),
        "last_category": last_category,
    }


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
async def post_session(
    request: Request, body: CreateSessionRequest | None = None
) -> dict:
    """Create a new session (= new checkpoint thread) and return its id.

    Optional body: ``{"initial_profile": {vibe, budget, categories}}`` — the
    E4 onboarding quiz answers. When present they are translated into a
    buyer_profiles row before the first turn so the Stylist's first reply is
    already shaped by the buyer's stated vibe / budget / category. A buyer who
    skips the quiz (or whose answers all fall to defaults) gets no profile row
    and the Preference Extractor populates it naturally as conversation
    unfolds — identical to pre-E4 behaviour.
    """

    settings = request.app.state.settings
    session_id = uuid4().hex
    await create_session(session_id, settings.shopify_store_domain)

    if body is not None and body.initial_profile is not None:
        seed = _profile_seed(body.initial_profile)
        if seed is not None:
            try:
                await upsert_buyer_profile(
                    session_id,
                    seed["sizes_json"],
                    seed["budget_min"],
                    seed["budget_max"],
                    seed["style_tags"],
                    seed["last_category"],
                )
            except Exception as exc:  # noqa: BLE001 - seed must never block session creation
                logger.warning(
                    "Failed to seed initial buyer profile for %s: %s",
                    session_id,
                    exc,
                )

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
