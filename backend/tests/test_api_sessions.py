"""Session endpoint tests — create, list (with preview), get, and 404.

All offline: the app is wired with FakeMCP tools and a MemorySaver graph over a
throwaway SQLite database (see ``make_api_client`` in conftest).
"""

from __future__ import annotations

from backend.db.queries import insert_message


async def test_create_session_returns_id(make_api_client):
    async with make_api_client() as (client, _app):
        resp = await client.post("/api/sessions")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"]
        assert isinstance(body["session_id"], str)


async def test_list_sessions_includes_created(make_api_client):
    async with make_api_client() as (client, _app):
        sid = (await client.post("/api/sessions")).json()["session_id"]

        resp = await client.get("/api/sessions")
        assert resp.status_code == 200
        sessions = resp.json()["sessions"]
        assert any(s["session_id"] == sid for s in sessions)


async def test_list_sessions_preview_is_first_message(make_api_client):
    async with make_api_client() as (client, _app):
        sid = (await client.post("/api/sessions")).json()["session_id"]
        await insert_message(sid, "user", "show me red summer dresses")

        sessions = (await client.get("/api/sessions")).json()["sessions"]
        row = next(s for s in sessions if s["session_id"] == sid)
        assert "red summer dresses" in row["preview"]


async def test_get_session_returns_messages(make_api_client):
    async with make_api_client() as (client, _app):
        sid = (await client.post("/api/sessions")).json()["session_id"]
        await insert_message(sid, "user", "hello there")

        resp = await client.get(f"/api/sessions/{sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == sid
        assert body["messages"][0]["role"] == "user"
        assert body["messages"][0]["content"] == "hello there"
        assert body["messages"][0]["events"] == []


async def test_get_unknown_session_returns_404(make_api_client):
    async with make_api_client() as (client, _app):
        resp = await client.get("/api/sessions/does-not-exist")
        assert resp.status_code == 404
