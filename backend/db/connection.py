"""Database connection management for Postgres (primary) and SQLite (HF Spaces).

Queries are written once against the Postgres dialect using ``%s`` placeholders
and ``now()`` for the current timestamp. Each backend is exposed through a thin
connection wrapper (:class:`PostgresConn` / :class:`SqliteConn`) implementing the
same async surface, so ``backend/db/queries.py`` stays backend-agnostic.

The SQLite wrapper performs lightweight textual translation of placeholders and
SQL functions; the Postgres wrapper passes statements through untouched.
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Sequence

import aiosqlite
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from backend.config import get_settings

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Lazily-initialised process singletons. Postgres uses a pooled set of
# connections; SQLite (single-process HF Spaces deployment) uses one shared
# connection guarded by aiosqlite's internal queue.
_pool: AsyncConnectionPool | None = None
_sqlite_conn: aiosqlite.Connection | None = None


# ---------------------------------------------------------------------------
# SQL translation helpers
# ---------------------------------------------------------------------------
def _to_sqlite(sql: str) -> str:
    """Translate a Postgres-dialect statement for SQLite execution.

    Only the constructs actually used by ``queries.py`` are handled: ``%s``
    placeholders become ``?`` and ``now()`` becomes ``CURRENT_TIMESTAMP``
    (valid both as a value expression and a column default in SQLite).
    """

    return sql.replace("%s", "?").replace("now()", "CURRENT_TIMESTAMP")


def _translate_schema_for_sqlite(sql: str) -> str:
    """Translate the canonical Postgres DDL into a SQLite-compatible script."""

    # `BIGSERIAL PRIMARY KEY` -> rowid autoincrement (handle the phrase as a
    # whole so we don't emit a duplicate PRIMARY KEY token).
    sql = re.sub(
        r"BIGSERIAL\s+PRIMARY\s+KEY",
        "INTEGER PRIMARY KEY AUTOINCREMENT",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(r"TIMESTAMPTZ", "TEXT", sql, flags=re.IGNORECASE)
    # SQLite rejects a bare function call as a column DEFAULT, but accepts the
    # CURRENT_TIMESTAMP keyword (UTC 'YYYY-MM-DD HH:MM:SS').
    sql = sql.replace("now()", "CURRENT_TIMESTAMP")
    return sql


def _split_statements(sql: str) -> list[str]:
    """Split a multi-statement script into individual statements.

    The schema contains no semicolons inside string literals, so a naive split
    is safe and avoids relying on multi-statement ``execute`` semantics.
    """

    return [stmt.strip() for stmt in sql.split(";") if stmt.strip()]


# ---------------------------------------------------------------------------
# Connection wrappers
# ---------------------------------------------------------------------------
class PostgresConn:
    """Async wrapper over a pooled psycopg connection (dict_row factory)."""

    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self._conn = conn

    async def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        async with self._conn.cursor() as cur:
            await cur.execute(sql, params)
            return await cur.fetchone()

    async def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        async with self._conn.cursor() as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        async with self._conn.cursor() as cur:
            await cur.execute(sql, params)

    async def insert_returning_id(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Run an ``INSERT ... RETURNING id`` and return the new id."""

        async with self._conn.cursor() as cur:
            await cur.execute(sql, params)
            row = await cur.fetchone()
            return int(row["id"])


class SqliteConn:
    """Async wrapper over the shared aiosqlite connection."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> dict | None:
        async with self._conn.execute(_to_sqlite(sql), params) as cur:
            row = await cur.fetchone()
            return dict(row) if row is not None else None

    async def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[dict]:
        async with self._conn.execute(_to_sqlite(sql), params) as cur:
            rows = await cur.fetchall()
            return [dict(row) for row in rows]

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        await self._conn.execute(_to_sqlite(sql), params)
        await self._conn.commit()

    async def insert_returning_id(self, sql: str, params: Sequence[Any] = ()) -> int:
        """SQLite has no RETURNING dependency here: strip it and use lastrowid."""

        statement = _to_sqlite(sql)
        marker = statement.upper().rfind(" RETURNING ")
        if marker != -1:
            statement = statement[:marker]
        cur = await self._conn.execute(statement, params)
        await self._conn.commit()
        return int(cur.lastrowid)


DBConn = PostgresConn | SqliteConn


# ---------------------------------------------------------------------------
# Pool / connection bootstrap
# ---------------------------------------------------------------------------
async def _get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        try:
            pool = AsyncConnectionPool(
                settings.database_url,
                min_size=1,
                max_size=10,
                timeout=30,
                open=False,
                kwargs={"row_factory": dict_row, "autocommit": True},
            )
            await pool.open(wait=True, timeout=10)
        except Exception as exc:  # pragma: no cover - surfaced to caller
            logger.error("Failed to open Postgres connection pool: %s", exc)
            raise RuntimeError(f"Could not connect to Postgres: {exc}") from exc
        _pool = pool
    return _pool


async def _get_sqlite_conn() -> aiosqlite.Connection:
    global _sqlite_conn
    if _sqlite_conn is None:
        settings = get_settings()
        path = settings.sqlite_path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        try:
            conn = await aiosqlite.connect(path)
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys = ON")
            await conn.commit()
        except Exception as exc:  # pragma: no cover - surfaced to caller
            logger.error("Failed to open SQLite database at %s: %s", path, exc)
            raise RuntimeError(f"Could not open SQLite database: {exc}") from exc
        _sqlite_conn = conn
    return _sqlite_conn


@asynccontextmanager
async def get_conn() -> AsyncIterator[DBConn]:
    """Yield a backend-appropriate connection wrapper.

    Postgres connections are checked out of the pool for the duration of the
    ``async with`` block and returned automatically. The SQLite connection is a
    shared singleton.
    """

    settings = get_settings()
    if settings.db_backend == "postgres":
        pool = await _get_pool()
        async with pool.connection() as raw:
            yield PostgresConn(raw)
    else:
        conn = await _get_sqlite_conn()
        yield SqliteConn(conn)


async def init_db() -> None:
    """Create all application tables. Safe to run repeatedly (idempotent)."""

    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    settings = get_settings()

    if settings.db_backend == "postgres":
        pool = await _get_pool()
        async with pool.connection() as conn:
            for statement in _split_statements(schema_sql):
                await conn.execute(statement)
        logger.info("Postgres schema initialised")
    else:
        conn = await _get_sqlite_conn()
        await conn.executescript(_translate_schema_for_sqlite(schema_sql))
        await conn.commit()
        logger.info("SQLite schema initialised at %s", settings.sqlite_path)


async def close_db() -> None:
    """Release pooled/shared connections. Used at shutdown and in tests."""

    global _pool, _sqlite_conn
    if _pool is not None:
        await _pool.close()
        _pool = None
    if _sqlite_conn is not None:
        await _sqlite_conn.close()
        _sqlite_conn = None
