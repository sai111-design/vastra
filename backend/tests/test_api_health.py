"""Health endpoint tests — shape and DB/MCP status reporting."""

from __future__ import annotations


async def test_health_reports_ok_shape(make_api_client):
    async with make_api_client() as (client, _app):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {"db", "mcp", "model"}
        # DB is the freshly-initialised SQLite file; MCP tools are wired at setup.
        assert body["db"] == "ok"
        assert body["mcp"] == "ok"
        assert body["model"] in ("groq", "gemini")


async def test_health_mcp_down_when_no_tools(make_api_client):
    async with make_api_client() as (client, app):
        app.state.tools_by_agent = {"stylist": [], "cart": [], "support": []}
        body = (await client.get("/api/health")).json()
        assert body["mcp"] == "down"
        assert body["db"] == "ok"


async def test_health_model_is_groq_with_key(make_api_client):
    async with make_api_client() as (client, _app):
        # sqlite_env sets GROQ_API_KEY, so the active primary provider is Groq.
        body = (await client.get("/api/health")).json()
        assert body["model"] == "groq"
