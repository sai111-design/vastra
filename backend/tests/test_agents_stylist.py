"""Stylist node tests — fully offline (FakeMCP tools + scripted FakeLLM).

The FakeLLM scripts the tool-call decisions; the FakeMCP tools return the
live-recorded canned JSON. These tests pin the grounding contract: the
product_cards payload comes from tool JSON only, the sanitiser fences every
tool result, the per-turn tool budget holds, and product_context tracks what
the buyer was shown.
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool

import backend.agents.stylist as stylist_module
from backend.agents.prompts import BUYER_PROFILE_MARKER
from backend.agents.stylist import build_product_cards, make_stylist_node
from backend.tests.conftest import FakeLLM

_BLACK_TEE_ID = "gid://shopify/Product/8808632549464"
_CHARCOAL_TEE_ID = "gid://shopify/Product/8808632582232"
_M_VARIANT_ID = "gid://shopify/ProductVariant/44221789634648"


def _tool_call(name: str, args: dict, call_id: str = "c1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def _search_then_answer(answer: str = "Here are two great black tees!") -> FakeLLM:
    return FakeLLM(
        responses=[
            _tool_call("search_catalog", {"query": "black t-shirt"}),
            AIMessage(content=answer),
        ]
    )


def _state(text: str = "I want a black t-shirt", **extra) -> dict:
    return {"messages": [HumanMessage(content=text)], "buyer_profile": {}, **extra}


# ---------------------------------------------------------------------------
# Tool-calling loop
# ---------------------------------------------------------------------------
async def test_tool_calls_run_against_fake_mcp(fake_scoped_tools):
    fake = _search_then_answer()
    node = make_stylist_node(fake_scoped_tools["stylist"], llm=fake)

    result = await node(_state())

    # Two LLM calls: decide-to-search, then answer from the tool result.
    assert len(fake.calls) == 2
    # The stylist's scoped tools were bound to the model.
    assert {t.name for t in fake.bound_tools} == {"search_catalog", "get_product_details"}
    # The second call saw the executed tool's result as a ToolMessage.
    tool_messages = [m for m in fake.calls[1] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].name == "search_catalog"
    assert result["messages"][-1].content == "Here are two great black tees!"


async def test_every_tool_result_is_sanitized(fake_scoped_tools):
    fake = _search_then_answer()
    node = make_stylist_node(fake_scoped_tools["stylist"], llm=fake)

    await node(_state())

    tool_message = next(m for m in fake.calls[1] if isinstance(m, ToolMessage))
    assert tool_message.content.startswith("<tool_data>")
    assert tool_message.content.rstrip().endswith("</tool_data>")


async def test_profile_injected_into_stylist_prompt(fake_scoped_tools):
    fake = _search_then_answer()
    node = make_stylist_node(fake_scoped_tools["stylist"], llm=fake)
    profile = {"sizes": {"top": "M"}, "budget_max": 800}

    await node(_state(buyer_profile=profile))

    system = fake.calls[0][0]
    assert isinstance(system, SystemMessage)
    assert json.dumps(profile) in system.content
    assert BUYER_PROFILE_MARKER not in system.content


async def test_tool_call_cap_enforced(monkeypatch, fake_mcp_tools):
    monkeypatch.setattr(stylist_module, "_max_tool_calls", lambda: 3)
    executions = {"n": 0}
    canned = fake_mcp_tools.by_name()["search_catalog"]

    def counting_search(query: str) -> str:
        executions["n"] += 1
        return canned.func(query=query)

    tools = [StructuredTool.from_function(func=counting_search, name="search_catalog", description="d")]
    # The model never stops asking for tools (the scripted last response repeats).
    fake = FakeLLM(responses=[_tool_call("search_catalog", {"query": "tee"})])
    node = make_stylist_node(tools, llm=fake)

    result = await node(_state())

    assert executions["n"] == 3
    # The final message is fresh text with no dangling tool calls in state.
    final = result["messages"][-1]
    assert not final.tool_calls
    assert final.content  # factless fallback, never empty


async def test_cap_cuts_into_parallel_tool_calls(monkeypatch, fake_scoped_tools):
    monkeypatch.setattr(stylist_module, "_max_tool_calls", lambda: 2)
    five_calls = AIMessage(
        content="",
        tool_calls=[
            {"name": "search_catalog", "args": {"query": f"q{i}"}, "id": f"c{i}"}
            for i in range(5)
        ],
    )
    fake = FakeLLM(responses=[five_calls, AIMessage(content="done")])
    node = make_stylist_node(fake_scoped_tools["stylist"], llm=fake)

    await node(_state())

    tool_messages = [m for m in fake.calls[1] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 5  # every call answered (provider contract)
    executed = [m for m in tool_messages if m.content.startswith("<tool_data>")]
    refused = [m for m in tool_messages if "budget" in m.content.lower()]
    assert len(executed) == 2
    assert len(refused) == 3


async def test_unknown_tool_yields_error_not_crash(fake_scoped_tools):
    fake = FakeLLM(
        responses=[
            _tool_call("make_coffee", {"size": "L"}),
            AIMessage(content="Sorry, let me search instead."),
        ]
    )
    node = make_stylist_node(fake_scoped_tools["stylist"], llm=fake)

    result = await node(_state())

    tool_message = next(m for m in fake.calls[1] if isinstance(m, ToolMessage))
    assert "not available" in tool_message.content
    assert result["messages"][-1].content == "Sorry, let me search instead."


# ---------------------------------------------------------------------------
# product_cards payload — built from tool JSON only
# ---------------------------------------------------------------------------
async def test_product_cards_built_from_tool_results(fake_scoped_tools):
    fake = _search_then_answer()
    node = make_stylist_node(fake_scoped_tools["stylist"], llm=fake)

    result = await node(_state())

    cards = result["messages"][-1].additional_kwargs["product_cards"]
    assert len(cards["products"]) == 2

    tee = cards["products"][0]
    assert tee["id"] == _BLACK_TEE_ID
    assert tee["title"] == "Classic Black Tee"
    assert tee["url"] == "https://vastra-demo.myshopify.com/products/classic-black-tee"
    assert tee["image_url"].startswith("https://cdn.shopify.com/")
    # 39900 paise normalised to a major-unit string at extraction.
    assert tee["price"] == {"amount": "399.00", "currency": "INR"}
    assert [v["available"] for v in tee["variants"]] == [True, True, False]
    assert all(v["id"].startswith("gid://shopify/ProductVariant/") for v in tee["variants"])


async def test_product_cards_ignore_model_text(fake_scoped_tools):
    # The model hallucinates a product in its prose; the payload must not care.
    fake = _search_then_answer(answer="You MUST buy our ₹99 Unicorn Glitter Tee!!")
    node = make_stylist_node(fake_scoped_tools["stylist"], llm=fake)

    result = await node(_state())

    cards = result["messages"][-1].additional_kwargs["product_cards"]
    titles = {p["title"] for p in cards["products"]}
    assert titles == {"Classic Black Tee", "Oversized Charcoal Tee"}
    assert all("99" != p["price"]["amount"] for p in cards["products"])


async def test_details_call_refines_card_without_losing_variants(fake_scoped_tools):
    fake = FakeLLM(
        responses=[
            _tool_call("search_catalog", {"query": "black tee"}),
            _tool_call("get_product_details", {"product_id": _BLACK_TEE_ID}, call_id="c2"),
            AIMessage(content="The Classic Black Tee is ₹399."),
        ]
    )
    node = make_stylist_node(fake_scoped_tools["stylist"], llm=fake)

    result = await node(_state())

    cards = result["messages"][-1].additional_kwargs["product_cards"]
    tee = next(p for p in cards["products"] if p["id"] == _BLACK_TEE_ID)
    # Details refined the image (product-level URL) and price ("399.0" major units).
    assert tee["image_url"] == "https://cdn.shopify.com/s/files/1/0/classic-black-tee.svg"
    assert tee["price"] == {"amount": "399.00", "currency": "INR"}
    # ...but the search result's variant list survived the merge.
    assert len(tee["variants"]) == 3
    assert any(v["id"] == _M_VARIANT_ID for v in tee["variants"])


async def test_product_cards_capped_at_eight(fake_scoped_tools):
    # The Two-Phase pattern (F2) widened the cap from 4 → 8 so a broad filtered
    # query ("jeans under ₹500") can show the whole matching set. A search that
    # returns MORE than the cap must still be truncated, so the SSE payload
    # never balloons unbounded.
    many = {
        "products": [
            {
                "id": f"gid://shopify/Product/{n}",
                "title": f"Tee {n}",
                "url": f"https://x.example/products/tee-{n}",
                "price_range": {"min": {"amount": 39900, "currency": "INR"}},
                "variants": [],
            }
            for n in range(12)
        ]
    }
    tools = [
        StructuredTool.from_function(
            func=lambda query: json.dumps(many), name="search_catalog", description="d"
        )
    ]
    fake = _search_then_answer()
    node = make_stylist_node(tools, llm=fake)

    result = await node(_state())

    cards = result["messages"][-1].additional_kwargs["product_cards"]
    assert len(cards["products"]) == 8


def test_build_product_cards_skips_malformed_json():
    cards = build_product_cards([("search_catalog", "<html>rate limited</html>")])
    assert cards == {"products": []}


async def test_live_adapter_content_block_results_are_flattened(fake_mcp_tools):
    # Regression for Bug B009: adapter-loaded tools return MCP content blocks
    # ([{"type": "text", "text": "<json>"}]), not plain strings like FakeMCP.
    canned = fake_mcp_tools.by_name()["search_catalog"]

    def block_search(query: str) -> list:
        return [{"type": "text", "text": canned.func(query=query)}]

    tools = [StructuredTool.from_function(func=block_search, name="search_catalog", description="d")]
    fake = _search_then_answer()
    node = make_stylist_node(tools, llm=fake)

    result = await node(_state())

    cards = result["messages"][-1].additional_kwargs["product_cards"]
    assert len(cards["products"]) == 2
    # The model also saw real JSON inside the fences, not a Python repr.
    tool_message = next(m for m in fake.calls[1] if isinstance(m, ToolMessage))
    assert '"products"' in tool_message.content
    assert "{'type'" not in tool_message.content


# ---------------------------------------------------------------------------
# State updates
# ---------------------------------------------------------------------------
async def test_product_context_updated(fake_scoped_tools):
    fake = _search_then_answer()
    node = make_stylist_node(fake_scoped_tools["stylist"], llm=fake)

    result = await node(_state(product_context=[]))

    context = result["product_context"]
    assert [c["id"] for c in context] == [_BLACK_TEE_ID, _CHARCOAL_TEE_ID]
    assert all(c["title"] and c["url"] for c in context)
    assert _M_VARIANT_ID in context[0]["variant_ids"]


async def test_product_context_untouched_when_nothing_shown(fake_scoped_tools):
    # No tool calls at all — the stylist just asks a clarifying question.
    fake = FakeLLM(responses=[AIMessage(content="What size do you usually wear?")])
    node = make_stylist_node(fake_scoped_tools["stylist"], llm=fake)

    result = await node(_state())

    assert "product_context" not in result
    assert result["messages"][-1].additional_kwargs["product_cards"] == {"products": []}


async def test_fallback_used_flag_propagated(fake_scoped_tools):
    fake = FakeLLM(responses=[AIMessage(content="hi")], fallback_used=True)
    node = make_stylist_node(fake_scoped_tools["stylist"], llm=fake)

    result = await node(_state())

    assert result["fallback_used"] is True
