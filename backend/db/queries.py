"""Hand-written, fully parameterised SQL operations for Vastra.

Every statement uses ``%s`` placeholders (translated to ``?`` for SQLite by the
connection wrapper) — there is zero string interpolation of user data into SQL.
All rows are returned as plain ``dict`` objects.
"""

from __future__ import annotations

from typing import Any

from backend.db.connection import get_conn

# Max characters of the first message surfaced as a session preview.
_PREVIEW_CHARS = 120

_SESSION_COLUMNS = "id, store_domain, cart_id, created_at, last_active"


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
async def create_session(session_id: str, store_domain: str) -> dict:
    """Insert a session and return the stored row (incl. id and created_at)."""

    async with get_conn() as conn:
        await conn.execute(
            "INSERT INTO sessions (id, store_domain) VALUES (%s, %s)",
            (session_id, store_domain),
        )
        return await conn.fetch_one(
            f"SELECT {_SESSION_COLUMNS} FROM sessions WHERE id = %s",
            (session_id,),
        )


async def get_session(session_id: str) -> dict | None:
    async with get_conn() as conn:
        return await conn.fetch_one(
            f"SELECT {_SESSION_COLUMNS} FROM sessions WHERE id = %s",
            (session_id,),
        )


async def list_sessions() -> list[dict]:
    """Return sessions newest-first, each with a truncated first-message preview."""

    async with get_conn() as conn:
        return await conn.fetch_all(
            """
            SELECT s.id, s.store_domain, s.cart_id, s.created_at, s.last_active,
                   (
                       SELECT substr(m.content, 1, %s)
                       FROM messages m
                       WHERE m.session_id = s.id
                       ORDER BY m.created_at ASC, m.id ASC
                       LIMIT 1
                   ) AS preview
            FROM sessions s
            ORDER BY s.last_active DESC
            """,
            (_PREVIEW_CHARS,),
        )


async def update_session_activity(session_id: str) -> None:
    """Touch ``last_active`` to mark recent interaction."""

    async with get_conn() as conn:
        await conn.execute(
            "UPDATE sessions SET last_active = now() WHERE id = %s",
            (session_id,),
        )


async def update_session_cart(session_id: str, cart_id: str) -> None:
    async with get_conn() as conn:
        await conn.execute(
            "UPDATE sessions SET cart_id = %s, last_active = now() WHERE id = %s",
            (cart_id, session_id),
        )


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
async def insert_message(
    session_id: str,
    role: str,
    content: str,
    events_json: str | None = None,
) -> int:
    async with get_conn() as conn:
        return await conn.insert_returning_id(
            "INSERT INTO messages (session_id, role, content, events_json) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (session_id, role, content, events_json),
        )


async def get_messages(session_id: str) -> list[dict]:
    async with get_conn() as conn:
        return await conn.fetch_all(
            "SELECT id, session_id, role, content, events_json, created_at "
            "FROM messages WHERE session_id = %s "
            "ORDER BY created_at ASC, id ASC",
            (session_id,),
        )


# ---------------------------------------------------------------------------
# Buyer profiles
# ---------------------------------------------------------------------------
async def upsert_buyer_profile(
    session_id: str,
    sizes_json: str,
    budget_min: int | None,
    budget_max: int | None,
    style_tags: str,
    last_category: str | None,
) -> None:
    """Insert a buyer profile, or update the existing one for this session."""

    async with get_conn() as conn:
        await conn.execute(
            """
            INSERT INTO buyer_profiles
                (session_id, sizes_json, budget_min, budget_max,
                 style_tags, last_category, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (session_id) DO UPDATE SET
                sizes_json    = EXCLUDED.sizes_json,
                budget_min    = EXCLUDED.budget_min,
                budget_max    = EXCLUDED.budget_max,
                style_tags    = EXCLUDED.style_tags,
                last_category = EXCLUDED.last_category,
                updated_at    = now()
            """,
            (session_id, sizes_json, budget_min, budget_max, style_tags, last_category),
        )


async def get_buyer_profile(session_id: str) -> dict | None:
    async with get_conn() as conn:
        return await conn.fetch_one(
            "SELECT session_id, sizes_json, budget_min, budget_max, "
            "style_tags, last_category, updated_at "
            "FROM buyer_profiles WHERE session_id = %s",
            (session_id,),
        )


# ---------------------------------------------------------------------------
# Tool-call log
# ---------------------------------------------------------------------------
async def log_tool_call(
    session_id: str,
    agent: str,
    tool_name: str,
    args_json: str,
    status: str,
    confirmed: bool | None,
    latency_ms: int | None,
) -> int:
    async with get_conn() as conn:
        return await conn.insert_returning_id(
            "INSERT INTO tool_call_log "
            "(session_id, agent, tool_name, args_json, status, confirmed, latency_ms) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (session_id, agent, tool_name, args_json, status, confirmed, latency_ms),
        )
