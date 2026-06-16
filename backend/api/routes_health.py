"""Liveness endpoint — reports DB, MCP, and active model-provider status.

The check is intentionally cheap: a ``SELECT 1`` for the database and a read of
the tools loaded at startup for MCP. ``load_scoped_tools`` performs a real
connection to the Storefront MCP during lifespan startup, so a populated
``tools_by_agent`` is the MCP liveness signal — we do not re-ping the live store
on every health request (that would add latency and an external dependency to a
probe that container orchestrators may hit frequently).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from backend.config import get_settings
from backend.db.connection import get_conn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["health"])


async def _check_db() -> str:
    """Return ``"ok"`` if a trivial query succeeds, else ``"down"``."""

    try:
        async with get_conn() as conn:
            await conn.fetch_one("SELECT 1 AS one")
        return "ok"
    except Exception as exc:  # noqa: BLE001 - health must never raise
        logger.warning("Health DB check failed: %s", exc)
        return "down"


def _check_mcp(request: Request) -> str:
    """Return ``"ok"`` if MCP tools were loaded at startup, else ``"down"``."""

    tools = getattr(request.app.state, "tools_by_agent", None)
    if isinstance(tools, dict) and tools.get("stylist"):
        return "ok"
    return "down"


def _active_model() -> str:
    """Report the active primary provider (Groq unless no key is configured)."""

    try:
        settings = get_settings()
        return "groq" if settings.groq_api_key else "gemini"
    except Exception:  # noqa: BLE001
        return "groq"


@router.get("/health")
async def health(request: Request) -> dict:
    """Report DB connectivity, MCP availability, and the active model provider."""

    return {
        "db": await _check_db(),
        "mcp": _check_mcp(request),
        "model": _active_model(),
    }
