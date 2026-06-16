"""Chat endpoint tests — SSE streaming, validation, checkpoint durability, memory.

All offline: a FakeMCP-scoped MemorySaver graph with scripted offline LLM seams.
The supervisor seam returns a route JSON; the stylist seam scripts a search
tool-call turn followed by a text reply.
"""

from __future__ import annotations

import asyncio
import json

from langchain_core.messages import AIMessage

from backend.tests.conftest import FakeLLM, parse_sse


def _supervisor(route: str = "stylist") -> FakeLLM:
    return FakeLLM(response=json.dumps({"route": route}))


def _stylist_search_then_reply() -> FakeLLM:
    return FakeLLM(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_catalog",
                        "args": {"query": "black tee"},
                        "id": "c1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="The Classic Black Tee at Rs399 is a great pick."),
        ]
    )


async def _new_session(client) -> str:
    return (await client.post("/api/sessions")).json()["session_id"]


async def test_chat_streams_token_route_cards_done(make_api_client):
    async with make_api_client(
        supervisor_llm=_supervisor("stylist"),
        stylist_llm=_stylist_search_then_reply(),
    ) as (client, _app):
        sid = await _new_session(client)

        resp = await client.post(
            "/api/chat", json={"session_id": sid, "message": "show me black tees"}
        )
        assert resp.status_code == 200

        events = parse_sse(resp.text)
        types = [e["event"] for e in events]
        assert "route" in types
        assert "token" in types
        assert "product_cards" in types
        assert "done" in types

        route = json.loads(next(e for e in events if e["event"] == "route")["data"])
        assert route["agent"] == "stylist"

        # Tokens reconstruct the grounded final reply.
        tokens = [
            json.loads(e["data"])["text"] for e in events if e["event"] == "token"
        ]
        assert "Classic Black Tee" in "".join(tokens)

        cards = json.loads(
            next(e for e in events if e["event"] == "product_cards")["data"]
        )
        assert cards["products"]
        assert cards["products"][0]["title"] == "Classic Black Tee"

        done = json.loads(next(e for e in events if e["event"] == "done")["data"])
        assert done["fallback_used"] is False
        assert done["turn_id"] is not None


async def test_chat_unknown_session_returns_404(make_api_client):
    async with make_api_client() as (client, _app):
        resp = await client.post(
            "/api/chat", json={"session_id": "nope", "message": "hi"}
        )
        assert resp.status_code == 404


async def test_chat_message_too_long_returns_400(make_api_client):
    async with make_api_client(supervisor_llm=_supervisor()) as (client, _app):
        sid = await _new_session(client)
        resp = await client.post(
            "/api/chat", json={"session_id": sid, "message": "x" * 1001}
        )
        assert resp.status_code == 400


async def test_chat_persists_message_history(make_api_client):
    async with make_api_client(
        supervisor_llm=_supervisor("stylist"),
        stylist_llm=_stylist_search_then_reply(),
    ) as (client, _app):
        sid = await _new_session(client)
        await client.post(
            "/api/chat", json={"session_id": sid, "message": "show me black tees"}
        )

        detail = (await client.get(f"/api/sessions/{sid}")).json()
        roles = [m["role"] for m in detail["messages"]]
        assert roles == ["user", "assistant"]
        assert detail["messages"][0]["content"] == "show me black tees"
        # The assistant message carries its structured events for replay.
        replay_types = [ev["event"] for ev in detail["messages"][1]["events"]]
        assert "route" in replay_types
        assert "product_cards" in replay_types


async def test_chat_checkpoint_shares_history_across_turns(make_api_client):
    async with make_api_client(
        supervisor_llm=_supervisor("stylist"),
        stylist_llm=_stylist_search_then_reply(),
    ) as (client, app):
        sid = await _new_session(client)
        await client.post(
            "/api/chat", json={"session_id": sid, "message": "first message"}
        )
        await client.post(
            "/api/chat", json={"session_id": sid, "message": "second message"}
        )

        # The checkpointer accumulated both turns under one thread_id.
        config = {"configurable": {"thread_id": sid}}
        state = await app.state.graph.aget_state(config)
        contents = [str(getattr(m, "content", "")) for m in state.values["messages"]]
        assert "first message" in contents
        assert "second message" in contents
        # Two human + two assistant messages survive (intra-turn scratchpad does not).
        assert len(state.values["messages"]) == 4


async def test_chat_runs_preference_extractor(make_api_client, monkeypatch):
    import backend.api.routes_chat as routes_chat
    from backend.db.queries import get_buyer_profile

    async def _fake_extract(_user, _assistant, **_kw):
        return {"sizes": {"top": "L"}, "last_category": "tshirts"}

    monkeypatch.setattr(routes_chat, "extract_preferences", _fake_extract)

    async with make_api_client(
        supervisor_llm=_supervisor("stylist"),
        stylist_llm=_stylist_search_then_reply(),
    ) as (client, app):
        sid = await _new_session(client)
        await client.post(
            "/api/chat", json={"session_id": sid, "message": "I wear size L tops"}
        )

        # Drain the fire-and-forget extraction task, then assert the DB upsert.
        await asyncio.gather(*list(app.state.bg_tasks), return_exceptions=True)
        profile = await get_buyer_profile(sid)
        assert profile is not None
        assert json.loads(profile["sizes_json"]) == {"top": "L"}
        assert profile["last_category"] == "tshirts"
