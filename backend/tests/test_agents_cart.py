"""Cart node tests — the interrupt/confirm safety gate, fully offline.

The cart node re-executes from the top on every interrupt resume (LangGraph
semantics), so these tests use a CONTENT-based fake LLM that decides from the
message window, not a call-count script — a script would diverge across the
re-run. Interrupt paths are driven through a compiled graph with a MemorySaver
checkpointer (interrupts only work inside a running graph with a checkpointer).
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

import backend.agents.supervisor as supervisor_module
from backend.agents.cart import _build_pending, cart_update_from_json
from backend.agents.graph import build_graph
from backend.tests.conftest import FakeLLM

_BLACK_TEE_ID = "gid://shopify/Product/8808632549464"
_VARIANT_M = "gid://shopify/ProductVariant/44221789634648"

_PRODUCT_CTX = [
    {
        "id": _BLACK_TEE_ID,
        "title": "Classic Black Tee",
        "url": "https://vastra-demo.myshopify.com/products/classic-black-tee",
        "price": {"amount": "399.00", "currency": "INR"},
        "variant_ids": [_VARIANT_M],
        "variants": [{"id": _VARIANT_M, "title": "M / Black"}],
    }
]


# ---------------------------------------------------------------------------
# Content-based fake LLM (deterministic across node re-execution)
# ---------------------------------------------------------------------------
class CartFakeLLM:
    """Decides purely from the message window, so the resume re-run replays.

    * A ToolMessage in the window means a cart tool already ran this turn ->
      summarise.
    * Otherwise pick the first action from the latest human text: "show"/"what's
      in" -> get_cart; anything else -> propose update_cart for the M variant.
    """

    def __init__(self) -> None:
        self.calls: list = []
        self.bound_tools: list = []
        self._fallback_used = False

    @property
    def fallback_used(self) -> bool:
        return self._fallback_used

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001 - mirrors FallbackChat
        self.bound_tools = list(tools)
        return self

    async def ainvoke(self, messages, **kwargs):  # noqa: ANN001
        self.calls.append(list(messages))
        if any(isinstance(m, ToolMessage) for m in messages):
            return AIMessage(content="All set — here's your updated cart.")
        text = ""
        for message in messages:
            if isinstance(message, HumanMessage):
                text = str(message.content)
        low = text.lower()
        if "show" in low or "what's in" in low or "see my cart" in low:
            return AIMessage(content="", tool_calls=[{"name": "get_cart", "args": {}, "id": "g1"}])
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "update_cart",
                    "args": {"add_items": [{"variant_id": _VARIANT_M, "quantity": 1}]},
                    "id": "u1",
                }
            ],
        )


def _spy_cart_tools(fake_mcp_tools):
    """Cart tools wrapping the canned bodies with execution counters."""

    canned = fake_mcp_tools.by_name()
    calls = {"update_cart": 0, "get_cart": 0}

    def _update_cart(cart_id=None, add_items=None):
        calls["update_cart"] += 1
        return canned["update_cart"].func(cart_id=cart_id, add_items=add_items)

    def _get_cart(cart_id=None):
        calls["get_cart"] += 1
        return canned["get_cart"].func(cart_id=cart_id)

    tools = [
        StructuredTool.from_function(
            func=_update_cart, name="update_cart", description="Add/update/remove cart lines."
        ),
        StructuredTool.from_function(
            func=_get_cart, name="get_cart", description="Read the cart."
        ),
    ]
    return tools, calls


def _cart_graph(monkeypatch, fake_mcp_tools, cart_llm):
    """Compile a graph routed to the Cart node, with a checkpointer for interrupts."""

    monkeypatch.setattr(
        supervisor_module, "_get_llm", lambda: FakeLLM(response='{"route": "cart"}')
    )
    tools, calls = _spy_cart_tools(fake_mcp_tools)
    tools_by_agent = {"stylist": [], "cart": tools, "support": []}
    graph = build_graph(tools_by_agent, checkpointer=MemorySaver(), cart_llm=cart_llm)
    return graph, calls


def _add_input():
    return {
        "messages": [HumanMessage(content="add the black tee to my cart")],
        "buyer_profile": {},
        "product_context": _PRODUCT_CTX,
    }


# ---------------------------------------------------------------------------
# Interrupt / confirm flow
# ---------------------------------------------------------------------------
async def test_cart_add_proposes_interrupt(monkeypatch, fake_mcp_tools):
    graph, calls = _cart_graph(monkeypatch, fake_mcp_tools, CartFakeLLM())
    config = {"configurable": {"thread_id": "t-add"}}

    out = await graph.ainvoke(_add_input(), config)

    # The graph paused on an interrupt carrying the pending action.
    assert "__interrupt__" in out
    pending = out["__interrupt__"][0].value
    assert "action_id" in pending
    assert pending["line"]["variant_id"] == _VARIANT_M
    assert pending["line"]["quantity"] == 1
    assert pending["line"]["title"] == "Classic Black Tee"
    # The gate sits BEFORE the mutation — update_cart has not run.
    assert calls["update_cart"] == 0


async def test_cart_pending_summary_restates_line(monkeypatch, fake_mcp_tools):
    graph, _ = _cart_graph(monkeypatch, fake_mcp_tools, CartFakeLLM())
    config = {"configurable": {"thread_id": "t-summary"}}

    out = await graph.ainvoke(_add_input(), config)

    summary = out["__interrupt__"][0].value["summary"]
    assert "Classic Black Tee" in summary
    assert "M / Black" in summary
    assert "399.00" in summary


async def test_cart_approved_calls_update_cart(monkeypatch, fake_mcp_tools):
    graph, calls = _cart_graph(monkeypatch, fake_mcp_tools, CartFakeLLM())
    config = {"configurable": {"thread_id": "t-yes"}}

    await graph.ainvoke(_add_input(), config)
    out = await graph.ainvoke(Command(resume={"approved": True}), config)

    assert calls["update_cart"] == 1
    final = out["messages"][-1]
    assert final.type == "ai"
    cart_update = final.additional_kwargs.get("cart_update")
    assert cart_update is not None
    assert cart_update["cart_id"]
    # Subtotal 119700 paise -> "1197.00" from the canned update result.
    assert cart_update["subtotal"] == "1197.00"
    assert cart_update["total_quantity"] == 3
    assert out.get("cart_snapshot") is not None
    assert out.get("cart_id") == cart_update["cart_id"]


async def test_cart_denied_returns_unchanged_and_no_mutation(monkeypatch, fake_mcp_tools):
    graph, calls = _cart_graph(monkeypatch, fake_mcp_tools, CartFakeLLM())
    config = {"configurable": {"thread_id": "t-no"}}

    await graph.ainvoke(_add_input(), config)
    out = await graph.ainvoke(Command(resume={"approved": False}), config)

    assert calls["update_cart"] == 0
    final = out["messages"][-1]
    assert final.type == "ai"
    assert "unchanged" in final.content.lower()
    assert "cart_update" not in final.additional_kwargs


async def test_show_cart_no_interrupt(monkeypatch, fake_mcp_tools):
    graph, calls = _cart_graph(monkeypatch, fake_mcp_tools, CartFakeLLM())
    config = {"configurable": {"thread_id": "t-show"}}

    out = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="show me my cart")],
            "buyer_profile": {},
            "product_context": [],
        },
        config,
    )

    # Read-only path: no interrupt, get_cart ran, update_cart did not.
    assert "__interrupt__" not in out
    assert calls["get_cart"] == 1
    assert calls["update_cart"] == 0
    cart_update = out["messages"][-1].additional_kwargs.get("cart_update")
    assert cart_update is not None
    assert cart_update["lines"]


# ---------------------------------------------------------------------------
# Pure helpers (no graph)
# ---------------------------------------------------------------------------
def test_build_pending_resolves_title_and_price_from_context():
    pending = _build_pending(
        {"add_items": [{"variant_id": _VARIANT_M, "quantity": 2}]}, _PRODUCT_CTX
    )
    assert pending["line"] == {
        "variant_id": _VARIANT_M,
        "quantity": 2,
        "title": "Classic Black Tee",
        "price": {"amount": "399.00", "currency": "INR"},
    }
    assert len(pending["action_id"]) == 8


def test_cart_update_from_json_normalises_paise():
    raw = json.dumps(
        {
            "cart_id": "gid://shopify/Cart/c1",
            "checkout_url": "https://x/cart/c1",
            "currency": "INR",
            "subtotal": 79800,
            "total_quantity": 2,
            "lines": [
                {
                    "line_id": "l1",
                    "variant_id": _VARIANT_M,
                    "title": "Classic Black Tee - M",
                    "quantity": 2,
                    "unit_price": 39900,
                    "line_price": 79800,
                }
            ],
        }
    )
    payload = cart_update_from_json(raw)
    assert payload["subtotal"] == "798.00"
    assert payload["lines"][0]["unit_price"] == "399.00"
    assert payload["lines"][0]["line_price"] == "798.00"


def test_cart_update_from_json_rejects_garbage():
    assert cart_update_from_json("<html>nope</html>") is None
    assert cart_update_from_json(json.dumps({"unrelated": True})) is None
