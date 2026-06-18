"""Outfit Builder (complete_look) tests — fully offline.

These pin the v1 behaviour: the planner returns two complementary categories,
the node issues one search_catalog call per category (≤ MAX_OUTFIT_SEARCHES),
the merged ``product_cards`` payload is tagged ``look_completion=True`` with
the planner's intro, ``last_cart_action_confirmed`` is cleared on every run,
and the safety paths (no product_context, planner failure, empty search
results) never crash the turn.
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage

from backend.agents.outfit import (
    MAX_OUTFIT_SEARCHES,
    _parse_plan,
    make_complete_look_node,
)
from backend.tests.conftest import FakeLLM, _SEARCH_CATALOG_RESULT


class _SpyTool:
    """Minimal stand-in for the StructuredTool surface the node uses.

    StructuredTool is a pydantic v2 model whose fields aren't settable via
    monkeypatch, so the easiest spy is a plain object exposing ``name`` and
    ``ainvoke``.
    """

    def __init__(self, name: str, response: str) -> None:
        self.name = name
        self._response = response
        self.calls: list[dict] = []

    async def ainvoke(self, args):  # noqa: ANN001 - mirrors LangChain signature
        self.calls.append(dict(args))
        return self._response


def _state(*, product_context=None, profile=None, message="complete the look"):
    return {
        "messages": [HumanMessage(content=message)],
        "buyer_profile": profile or {},
        "product_context": product_context or [],
    }


_TEE_CONTEXT = [
    {
        "id": "gid://shopify/Product/8808632549464",
        "title": "Classic Black Tee",
        "url": "https://vastra-demo.myshopify.com/products/classic-black-tee",
        "price": {"amount": "399.00", "currency": "INR"},
        "variant_ids": ["gid://shopify/ProductVariant/44221789634648"],
        "variants": [{"id": "gid://shopify/ProductVariant/44221789634648", "title": "M / Black"}],
    }
]


# ---------------------------------------------------------------------------
# _parse_plan — the planner JSON contract
# ---------------------------------------------------------------------------
def test_parse_plan_extracts_intro_and_two_categories():
    intro, cats = _parse_plan(
        '{"intro": "Here\'s a clean pairing.", "categories": ["denim jeans", "white sneakers"]}'
    )
    assert intro == "Here's a clean pairing."
    assert cats == ["denim jeans", "white sneakers"]


def test_parse_plan_caps_categories_at_two():
    _, cats = _parse_plan('{"intro": "x", "categories": ["a", "b", "c", "d"]}')
    assert len(cats) == MAX_OUTFIT_SEARCHES
    assert cats == ["a", "b"]


def test_parse_plan_dedupes_categories_case_insensitive():
    _, cats = _parse_plan('{"intro": "x", "categories": ["Denim Jeans", "denim jeans", "white sneakers"]}')
    assert cats == ["Denim Jeans", "white sneakers"]


def test_parse_plan_tolerates_code_fences():
    intro, cats = _parse_plan('```json\n{"intro": "ok", "categories": ["belts"]}\n```')
    assert intro == "ok"
    assert cats == ["belts"]


def test_parse_plan_returns_empty_for_garbage():
    intro, cats = _parse_plan("I think jeans and sneakers would look great.")
    assert intro == ""
    assert cats == []


def test_parse_plan_returns_empty_for_non_object():
    intro, cats = _parse_plan('["jeans", "sneakers"]')
    assert intro == ""
    assert cats == []


# ---------------------------------------------------------------------------
# Node integration
# ---------------------------------------------------------------------------
async def test_complete_look_route_runs_two_searches_and_tags_payload():
    """The happy path: planner → 2 searches → look_completion payload."""

    plan_reply = json.dumps({
        "intro": "Great pick! Here's what pairs well with it:",
        "categories": ["denim jeans", "white sneakers"],
    })
    llm = FakeLLM(response=plan_reply)
    search_tool = _SpyTool("search_catalog", json.dumps(_SEARCH_CATALOG_RESULT))

    node = make_complete_look_node([search_tool], llm=llm)
    result = await node(_state(product_context=_TEE_CONTEXT))

    # Two and only two searches issued, one per category, with the category
    # text dropped into the query.
    assert len(search_tool.calls) == MAX_OUTFIT_SEARCHES == 2
    queries = sorted(call.get("query", "") for call in search_tool.calls)
    assert queries == ["denim jeans", "white sneakers"]

    # Final message carries the look_completion-tagged product cards.
    final = result["messages"][0]
    assert isinstance(final, AIMessage)
    payload = final.additional_kwargs["product_cards"]
    assert payload["look_completion"] is True
    assert payload["look_intro"] == "Great pick! Here's what pairs well with it:"
    assert payload["products"], "merged product cards should be non-empty"
    # Reply text matches the intro so the chat bubble doesn't go silent.
    assert "Great pick" in final.content

    # The flag is cleared so the supervisor's "post-cart" lean doesn't fire
    # again on the very next turn.
    assert result["last_cart_action_confirmed"] is False

    # product_context is refreshed so the buyer can immediately add a paired
    # piece without re-searching.
    assert "product_context" in result
    assert result["product_context"]


async def test_complete_look_no_product_context_replies_softly():
    """No grounding → never call any tool; reply asking for a specific piece."""

    llm = FakeLLM(response='{"intro": "ignored", "categories": ["a", "b"]}')
    search_tool = _SpyTool("search_catalog", json.dumps(_SEARCH_CATALOG_RESULT))

    node = make_complete_look_node([search_tool], llm=llm)
    result = await node(_state(product_context=[]))

    assert search_tool.calls == [], "no product_context should skip the tool entirely"
    assert "tell me" in result["messages"][0].content.lower()
    assert result["last_cart_action_confirmed"] is False


async def test_complete_look_planner_failure_replies_no_results():
    """A garbage planner reply → no searches, soft "couldn't find" message."""

    llm = FakeLLM(response="I would suggest some jeans, maybe sneakers, idk!")
    search_tool = _SpyTool("search_catalog", "")

    node = make_complete_look_node([search_tool], llm=llm)
    result = await node(_state(product_context=_TEE_CONTEXT))

    assert search_tool.calls == []
    final = result["messages"][0]
    assert "product_cards" not in (getattr(final, "additional_kwargs", {}) or {})
    assert result["last_cart_action_confirmed"] is False


async def test_complete_look_search_returning_nothing_replies_softly():
    """Planner produces categories but searches return no parseable JSON."""

    llm = FakeLLM(response=json.dumps({"intro": "x", "categories": ["a", "b"]}))
    search_tool = _SpyTool("search_catalog", "")

    node = make_complete_look_node([search_tool], llm=llm)
    result = await node(_state(product_context=_TEE_CONTEXT))

    final = result["messages"][0]
    assert "couldn't" in final.content.lower() or "could not" in final.content.lower()
    assert result["last_cart_action_confirmed"] is False


async def test_complete_look_clears_post_cart_flag_when_search_tool_missing():
    """Defensive: even if the scope has no search tool, the flag clears."""

    llm = FakeLLM(response=json.dumps({"intro": "x", "categories": ["a"]}))
    node = make_complete_look_node([], llm=llm)
    result = await node(_state(product_context=_TEE_CONTEXT))
    assert result["last_cart_action_confirmed"] is False
