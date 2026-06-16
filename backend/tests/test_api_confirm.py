"""Confirm endpoint tests — interrupt/resume cart flow over SSE.

Drives the full safety gate through HTTP: a stylist turn seeds product_context
into the checkpoint, a cart-add turn pauses on the interrupt and emits
``confirm_request``, then ``/api/confirm`` resumes the graph and streams
``cart_update``. Stale / mismatched confirmations return 409.

The cart node re-executes from the top on resume, so the cart LLM seam is the
content-based ``CartFakeLLM`` from the Stage 5 cart tests (a call-count script
would diverge across the re-run).
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage

from backend.tests.conftest import FakeLLM, parse_sse
from backend.tests.test_agents_cart import CartFakeLLM


def _supervisor_stylist_then_cart() -> FakeLLM:
    # Turn 1 (seed) -> stylist; turn 2 (cart add) -> cart. /confirm does not
    # re-enter the supervisor.
    return FakeLLM(
        responses=[
            AIMessage(content=json.dumps({"route": "stylist"})),
            AIMessage(content=json.dumps({"route": "cart"})),
        ]
    )


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


def _make_llms():
    return {
        "supervisor_llm": _supervisor_stylist_then_cart(),
        "stylist_llm": _stylist_search_then_reply(),
        "cart_llm": CartFakeLLM(),
    }


async def _drive_to_confirm_request(client) -> tuple[str, str]:
    """Create a session, seed product_context, propose a cart add; return (sid, action_id)."""

    sid = (await client.post("/api/sessions")).json()["session_id"]

    seed = await client.post(
        "/api/chat", json={"session_id": sid, "message": "show me black tees"}
    )
    assert "product_cards" in [e["event"] for e in parse_sse(seed.text)]

    add = await client.post(
        "/api/chat", json={"session_id": sid, "message": "add the black tee to my cart"}
    )
    events = parse_sse(add.text)
    types = [e["event"] for e in events]
    assert "confirm_request" in types
    # The turn is paused — no done yet, no cart mutation.
    assert "done" not in types
    assert "cart_update" not in types

    pending = json.loads(next(e for e in events if e["event"] == "confirm_request")["data"])
    assert "Classic Black Tee" in pending["summary"]
    assert pending["line"]["title"] == "Classic Black Tee"
    return sid, pending["action_id"]


async def test_confirm_approved_streams_cart_update(make_api_client):
    async with make_api_client(**_make_llms()) as (client, _app):
        sid, action_id = await _drive_to_confirm_request(client)

        resp = await client.post(
            "/api/confirm",
            json={"session_id": sid, "action_id": action_id, "approved": True},
        )
        assert resp.status_code == 200

        events = parse_sse(resp.text)
        types = [e["event"] for e in events]
        assert "cart_update" in types
        assert "done" in types

        cart = json.loads(next(e for e in events if e["event"] == "cart_update")["data"])
        assert cart["cart_id"]
        assert cart["subtotal"] == "1197.00"
        assert cart["total_quantity"] == 3


async def test_confirm_denied_leaves_cart_unchanged(make_api_client):
    async with make_api_client(**_make_llms()) as (client, _app):
        sid, action_id = await _drive_to_confirm_request(client)

        resp = await client.post(
            "/api/confirm",
            json={"session_id": sid, "action_id": action_id, "approved": False},
        )
        assert resp.status_code == 200

        events = parse_sse(resp.text)
        types = [e["event"] for e in events]
        assert "cart_update" not in types
        assert "done" in types
        tokens = "".join(
            json.loads(e["data"])["text"] for e in events if e["event"] == "token"
        )
        assert "unchanged" in tokens.lower()


async def test_confirm_stale_action_returns_409(make_api_client):
    async with make_api_client(**_make_llms()) as (client, _app):
        sid, action_id = await _drive_to_confirm_request(client)

        first = await client.post(
            "/api/confirm",
            json={"session_id": sid, "action_id": action_id, "approved": True},
        )
        assert first.status_code == 200

        # The interrupt is resolved — a repeat confirm is stale.
        second = await client.post(
            "/api/confirm",
            json={"session_id": sid, "action_id": action_id, "approved": True},
        )
        assert second.status_code == 409


async def test_confirm_wrong_action_id_returns_409(make_api_client):
    async with make_api_client(**_make_llms()) as (client, _app):
        sid, _action_id = await _drive_to_confirm_request(client)

        resp = await client.post(
            "/api/confirm",
            json={"session_id": sid, "action_id": "deadbeef", "approved": True},
        )
        assert resp.status_code == 409


async def test_confirm_unknown_session_returns_404(make_api_client):
    async with make_api_client(**_make_llms()) as (client, _app):
        resp = await client.post(
            "/api/confirm",
            json={"session_id": "nope", "action_id": "abc12345", "approved": True},
        )
        assert resp.status_code == 404
