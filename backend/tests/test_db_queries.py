"""Database query tests.

Postgres tests run against the live container (DB_BACKEND=postgres). Each test
creates a uniquely-keyed session and the fixture deletes it afterwards; the
ON DELETE CASCADE foreign keys clean up the dependent rows.

The final test exercises the SQLite translation path end-to-end against a
throw-away file database.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

import backend.db.connection as connection
from backend.config import get_settings
from backend.db import queries
from backend.db.connection import close_db, get_conn, init_db


# ---------------------------------------------------------------------------
# Postgres fixtures
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="session")
async def pg_schema():
    """Create the schema once for the Postgres test session.

    Explicitly requested (NOT autouse) so the Postgres gate only applies to the
    tests that actually need Postgres — ``test_sqlite_translation_path`` runs
    regardless of the configured backend.
    """

    if get_settings().db_backend != "postgres":
        pytest.skip("Postgres backend not configured")
    await init_db()
    # Second call proves idempotency — must not raise.
    await init_db()
    yield
    await close_db()


@pytest_asyncio.fixture
async def session_id(pg_schema):
    """Yield a fresh session id and delete it (cascading) on teardown."""

    sid = "pg-" + uuid.uuid4().hex
    yield sid
    async with get_conn() as conn:
        await conn.execute("DELETE FROM sessions WHERE id = %s", (sid,))


# ---------------------------------------------------------------------------
# Postgres tests
# ---------------------------------------------------------------------------
async def test_create_session_returns_row(session_id):
    row = await queries.create_session(session_id, "demo.myshopify.com")
    assert row["id"] == session_id
    assert row["store_domain"] == "demo.myshopify.com"
    assert row["created_at"] is not None
    assert row["cart_id"] is None


async def test_get_session_roundtrip(session_id):
    assert await queries.get_session(session_id) is None
    await queries.create_session(session_id, "demo.myshopify.com")
    fetched = await queries.get_session(session_id)
    assert fetched["id"] == session_id


async def test_update_session_cart(session_id):
    await queries.create_session(session_id, "demo.myshopify.com")
    await queries.update_session_cart(session_id, "gid://shopify/Cart/abc123")
    fetched = await queries.get_session(session_id)
    assert fetched["cart_id"] == "gid://shopify/Cart/abc123"


async def test_insert_and_get_messages(session_id):
    await queries.create_session(session_id, "demo.myshopify.com")
    first_id = await queries.insert_message(session_id, "user", "show me black tees")
    second_id = await queries.insert_message(
        session_id, "assistant", "Here are some options", '{"events": []}'
    )
    assert isinstance(first_id, int)
    assert second_id > first_id

    messages = await queries.get_messages(session_id)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "show me black tees"
    assert messages[1]["events_json"] == '{"events": []}'


async def test_upsert_buyer_profile_insert_then_update(session_id):
    await queries.create_session(session_id, "demo.myshopify.com")

    # First call inserts.
    await queries.upsert_buyer_profile(
        session_id, '{"top": "M"}', 500, 1500, '["streetwear"]', "tshirts"
    )
    profile = await queries.get_buyer_profile(session_id)
    assert profile["budget_min"] == 500
    assert profile["last_category"] == "tshirts"

    # Second call updates the same row.
    await queries.upsert_buyer_profile(
        session_id, '{"top": "L"}', 800, 2000, '["formal"]', "kurtas"
    )
    profile = await queries.get_buyer_profile(session_id)
    assert profile["sizes_json"] == '{"top": "L"}'
    assert profile["budget_max"] == 2000
    assert profile["last_category"] == "kurtas"


async def test_log_tool_call_returns_id(session_id):
    await queries.create_session(session_id, "demo.myshopify.com")
    log_id = await queries.log_tool_call(
        session_id, "stylist", "search_catalog", '{"query": "tee"}', "ok", None, 42
    )
    assert isinstance(log_id, int)
    assert log_id > 0


async def test_list_sessions_order_and_preview(pg_schema):
    older = "pg-" + uuid.uuid4().hex
    newer = "pg-" + uuid.uuid4().hex
    try:
        await queries.create_session(older, "demo.myshopify.com")
        await queries.insert_message(older, "user", "first message in older session")
        await queries.create_session(newer, "demo.myshopify.com")
        # Touch newer so it is unambiguously the most recently active.
        await queries.update_session_activity(newer)

        sessions = await queries.list_sessions()
        ids = [s["id"] for s in sessions]
        assert newer in ids and older in ids
        # newer must appear before older (reverse-chronological by last_active).
        assert ids.index(newer) < ids.index(older)

        older_row = next(s for s in sessions if s["id"] == older)
        assert older_row["preview"] == "first message in older session"
        newer_row = next(s for s in sessions if s["id"] == newer)
        assert newer_row["preview"] is None  # no messages yet
    finally:
        async with get_conn() as conn:
            await conn.execute(
                "DELETE FROM sessions WHERE id IN (%s, %s)", (older, newer)
            )


# ---------------------------------------------------------------------------
# SQLite translation path (defined last so it cleans up its own globals)
# ---------------------------------------------------------------------------
async def test_sqlite_translation_path(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "vastra_test.db"))
    get_settings.cache_clear()
    connection._sqlite_conn = None

    try:
        # init_db twice proves the translated DDL is valid and idempotent.
        await init_db()
        await init_db()

        sid = "sqlite-" + uuid.uuid4().hex
        session = await queries.create_session(sid, "demo.myshopify.com")
        assert session["id"] == sid
        assert session["created_at"] is not None

        msg_id = await queries.insert_message(sid, "user", "hello sqlite")
        assert isinstance(msg_id, int)
        messages = await queries.get_messages(sid)
        assert len(messages) == 1
        assert messages[0]["content"] == "hello sqlite"

        await queries.upsert_buyer_profile(sid, "{}", 300, 999, "[]", "sneakers")
        await queries.upsert_buyer_profile(sid, "{}", 300, 1299, "[]", "sneakers")
        profile = await queries.get_buyer_profile(sid)
        assert profile["budget_max"] == 1299

        log_id = await queries.log_tool_call(
            sid, "support", "search_shop_policies_and_faqs", "{}", "ok", True, 8
        )
        assert isinstance(log_id, int)

        sessions = await queries.list_sessions()
        row = next(s for s in sessions if s["id"] == sid)
        assert row["preview"] == "hello sqlite"
    finally:
        if connection._sqlite_conn is not None:
            await connection._sqlite_conn.close()
            connection._sqlite_conn = None
        get_settings.cache_clear()
