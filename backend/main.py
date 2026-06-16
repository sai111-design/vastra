"""FastAPI application factory and lifespan.

Startup wires the whole backend together: initialise the database schema, load
the scoped MCP tools from the live Storefront endpoint, open a checkpointer
(AsyncPostgresSaver locally / AsyncSqliteSaver on HF Spaces) and create its
LangGraph tables, then build the supervisor graph and stash everything on
``app.state`` for the route handlers.

The module exposes ``app = create_app()`` so the server can be started with
``uvicorn backend.main:app``. ``create_app`` also accepts a custom ``lifespan``
so tests can inject offline fakes (FakeMCP tools + a MemorySaver-backed graph)
without touching the network — note that httpx's ASGITransport does not run
lifespan events at all, so the offline test suite sets ``app.state`` directly
instead (see ``backend/tests/conftest.py``).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.agents.graph import build_graph
from backend.config import get_settings
from backend.db.connection import close_db, init_db
from backend.mcp.client import load_scoped_tools

logger = logging.getLogger(__name__)

# psycopg's async path (and the AsyncPostgresSaver, which uses psycopg) cannot
# run on the Windows ProactorEventLoop. Force the SelectorEventLoop policy at
# import so ``uvicorn backend.main:app`` works on a Windows dev box (a no-op on
# Linux/Docker, where the default loop is already compatible). See Bug B004.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _make_checkpointer(settings):
    """Return the checkpointer async context manager for the configured backend."""

    if settings.db_backend == "postgres":
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        return AsyncPostgresSaver.from_conn_string(settings.database_url)

    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    return AsyncSqliteSaver.from_conn_string(settings.sqlite_path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown — see module docstring."""

    settings = get_settings()
    await init_db()
    tools_by_agent = await load_scoped_tools(settings.shopify_store_domain)

    async with _make_checkpointer(settings) as checkpointer:
        await checkpointer.setup()  # idempotent: creates LangGraph checkpoint tables

        app.state.settings = settings
        app.state.tools_by_agent = tools_by_agent
        app.state.graph = build_graph(tools_by_agent, checkpointer)
        app.state.bg_tasks = set()
        logger.info("Vastra API ready (db=%s)", settings.db_backend)

        try:
            yield
        finally:
            await close_db()


def _install_cors(app: FastAPI) -> None:
    try:
        origin = get_settings().cors_origin
    except Exception:  # noqa: BLE001 - never block app creation on config read
        origin = "*"
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def create_app(lifespan=lifespan) -> FastAPI:
    """Build the FastAPI app: CORS + all ``/api`` routers.

    Args:
        lifespan: Override the startup/shutdown context (tests inject offline
            fakes; production uses the module-level :func:`lifespan`).
    """

    app = FastAPI(title="Vastra API", version="0.6.0", lifespan=lifespan)
    _install_cors(app)

    # Imported here so create_app stays import-safe even if a router module
    # pulls in optional deps at import time.
    from backend.api.routes_chat import router as chat_router
    from backend.api.routes_health import router as health_router
    from backend.api.routes_sessions import router as sessions_router

    app.include_router(sessions_router)
    app.include_router(chat_router)
    app.include_router(health_router)
    return app


app = create_app()
