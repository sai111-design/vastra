"""Supervisor node tests — fully offline (FakeLLM + FakeMCP, no network).

The FakeLLM scripts the classification the model would return; these tests
exercise the node's plumbing (prompt construction, window trimming, JSON
parsing, the stylist default) rather than real model judgement, which is
verified live through scripts/cli_chat.py.
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

import backend.agents.supervisor as supervisor_module
from backend.agents.graph import build_graph
from backend.agents.prompts import BUYER_PROFILE_MARKER
from backend.agents.supervisor import parse_route, supervisor_node, trim_messages
from backend.tests.conftest import FakeLLM


def _patch_llm(monkeypatch, fake: FakeLLM) -> None:
    monkeypatch.setattr(supervisor_module, "_get_llm", lambda: fake)


def _state(text: str, **extra) -> dict:
    return {"messages": [HumanMessage(content=text)], "buyer_profile": {}, **extra}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
async def test_discovery_routes_to_stylist(monkeypatch):
    _patch_llm(monkeypatch, FakeLLM(response='{"route": "stylist"}'))
    result = await supervisor_node(_state("I want a black t-shirt"))
    assert result["route"] == "stylist"


async def test_transaction_routes_to_cart(monkeypatch):
    _patch_llm(monkeypatch, FakeLLM(response='{"route": "cart"}'))
    result = await supervisor_node(_state("Add that to my cart"))
    assert result["route"] == "cart"


async def test_policy_routes_to_support(monkeypatch):
    _patch_llm(monkeypatch, FakeLLM(response='{"route": "support"}'))
    result = await supervisor_node(_state("What's your return policy?"))
    assert result["route"] == "support"


async def test_greeting_routes_to_respond(monkeypatch):
    _patch_llm(monkeypatch, FakeLLM(response='{"route": "respond"}'))
    result = await supervisor_node(_state("Thanks!"))
    assert result["route"] == "respond"


async def test_malformed_response_defaults_to_stylist(monkeypatch):
    _patch_llm(monkeypatch, FakeLLM(response="hmm, probably shopping related?"))
    result = await supervisor_node(_state("anything"))
    assert result["route"] == "stylist"


async def test_turn_count_increments(monkeypatch):
    _patch_llm(monkeypatch, FakeLLM(response='{"route": "respond"}'))
    result = await supervisor_node(_state("hi", turn_count=6))
    assert result["turn_count"] == 7


async def test_profile_injected_into_system_prompt(monkeypatch):
    fake = FakeLLM(response='{"route": "stylist"}')
    _patch_llm(monkeypatch, fake)
    profile = {"sizes": {"top": "M"}, "budget_max": 1000}

    await supervisor_node({"messages": [HumanMessage(content="jeans?")], "buyer_profile": profile})

    system = fake.calls[0][0]
    assert isinstance(system, SystemMessage)
    assert json.dumps(profile) in system.content
    assert BUYER_PROFILE_MARKER not in system.content


# ---------------------------------------------------------------------------
# parse_route
# ---------------------------------------------------------------------------
def test_parse_route_accepts_bare_json():
    assert parse_route('{"route": "support"}') == "support"


def test_parse_route_tolerates_code_fences():
    assert parse_route('```json\n{"route": "cart"}\n```') == "cart"


def test_parse_route_tolerates_surrounding_prose():
    assert parse_route('Sure! {"route": "respond"} — classified.') == "respond"


def test_parse_route_rejects_unknown_route_name():
    assert parse_route('{"route": "concierge"}') == "stylist"


def test_parse_route_handles_non_object_json():
    assert parse_route('["stylist"]') == "stylist"
    assert parse_route("") == "stylist"


# ---------------------------------------------------------------------------
# trim_messages
# ---------------------------------------------------------------------------
def test_trim_keeps_everything_under_budget():
    messages = [SystemMessage(content="sys"), HumanMessage(content="a"), AIMessage(content="b")]
    assert trim_messages(messages, budget=10_000) == messages


def test_trim_drops_middle_keeps_system_and_newest():
    system = SystemMessage(content="sys")
    old = [HumanMessage(content="x" * 400), AIMessage(content="y" * 400)]
    new = [HumanMessage(content="latest question")]
    # Budget fits the system prompt + the newest message only.
    trimmed = trim_messages([system, *old, *new], budget=30)
    assert trimmed[0] is system
    assert trimmed[-1] is new[0]
    assert not any(m in trimmed for m in old)


def test_trim_always_keeps_newest_even_over_budget():
    huge = HumanMessage(content="z" * 10_000)
    trimmed = trim_messages([SystemMessage(content="sys"), huge], budget=5)
    assert huge in trimmed


def test_trim_empty_list():
    assert trim_messages([], budget=100) == []


# ---------------------------------------------------------------------------
# Graph wiring (compiled-graph smoke tests, still offline)
# ---------------------------------------------------------------------------
async def test_graph_routes_discovery_through_stylist(monkeypatch, fake_scoped_tools):
    _patch_llm(monkeypatch, FakeLLM(response='{"route": "stylist"}'))
    stylist_llm = FakeLLM(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "search_catalog", "args": {"query": "black tee"}, "id": "c1"}]),
            AIMessage(content="Two black tees coming up!"),
        ]
    )
    graph = build_graph(fake_scoped_tools, stylist_llm=stylist_llm)

    out = await graph.ainvoke({"messages": [HumanMessage(content="I want a black t-shirt")]})

    assert out["route"] == "stylist"
    final = out["messages"][-1]
    assert final.content == "Two black tees coming up!"
    assert final.additional_kwargs["product_cards"]["products"]


async def test_graph_respond_ends_without_specialist(monkeypatch, fake_scoped_tools):
    _patch_llm(monkeypatch, FakeLLM(response='{"route": "respond"}'))
    graph = build_graph(fake_scoped_tools, stylist_llm=FakeLLM())

    out = await graph.ainvoke({"messages": [HumanMessage(content="Thanks!")]})

    assert out["route"] == "respond"
    # No specialist ran: the only message is still the buyer's.
    assert [m.type for m in out["messages"]] == ["human"]


async def test_graph_unwired_route_ends_cleanly(monkeypatch, fake_scoped_tools):
    # "cart" is a legal classification with no node until Stage 5 — the graph
    # must end the turn, not raise.
    _patch_llm(monkeypatch, FakeLLM(response='{"route": "cart"}'))
    graph = build_graph(fake_scoped_tools, stylist_llm=FakeLLM())

    out = await graph.ainvoke({"messages": [HumanMessage(content="Add that to my cart")]})

    assert out["route"] == "cart"
    assert [m.type for m in out["messages"]] == ["human"]
