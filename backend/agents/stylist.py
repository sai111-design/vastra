"""Stylist specialist — product discovery over the live catalog.

``make_stylist_node(tools)`` returns an async LangGraph node that runs a
bounded ReAct loop: the model may call its scoped MCP tools (search_catalog,
get_product_details) up to ``MAX_TOOL_CALLS_PER_TURN`` times, every tool
result is fenced by ``sanitize_tool_output`` before the model sees it, and the
turn ends with a single assistant message.

Grounding contract: the ``product_cards`` payload attached to the final
message is built ONLY from the raw JSON the tools returned this turn — never
from the model's text. The model writes prose; the tools supply every price,
URL, image, and variant id.

The intra-turn scratchpad (assistant tool-call messages + tool results) is
deliberately NOT written back into graph state: checkpointed history stays
small, and no assistant message with dangling ``tool_calls`` can poison the
next turn's provider request. What the buyer was shown survives the turn in
``product_context`` instead.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from backend.agents.prompts import BUYER_PROFILE_MARKER, STYLIST_PROMPT
from backend.agents.state import VastraState
from backend.agents.supervisor import _message_text, trim_messages
from backend.config import get_settings
from backend.llm.fallback import FallbackChat
from backend.mcp.sanitize import sanitize_tool_output

logger = logging.getLogger(__name__)

MAX_PRODUCT_CARDS = 4

# Told to the model when its tool budget runs out mid-plan, so it answers from
# the data it already has instead of stalling on an unanswered tool call.
_BUDGET_EXHAUSTED_MSG = (
    "Tool-call budget for this turn is exhausted. Answer the buyer now using "
    "only the tool data you already received."
)

# Factless fallbacks for the rare case the model returns tool calls but no
# prose even after being told the budget is gone. They make no product claims,
# so the grounding rules hold.
_FALLBACK_WITH_PRODUCTS = "Here are the products I found for you."
_FALLBACK_NO_PRODUCTS = (
    "I couldn't complete that search — could you tell me a bit more about "
    "what you're looking for?"
)


def _content_to_text(raw: Any) -> str:
    """Flatten an MCP tool result to the text it carries.

    langchain-mcp-adapters tools (``response_format="content_and_artifact"``)
    return a LIST of MCP content blocks (``[{"type": "text", "text": ...}]``)
    when invoked directly — found live in Stage 4 (Bug B009). ``str()`` on that
    list yields a Python repr that breaks ``json.loads``. Handles plain
    strings, lists of blocks, and lists of strings.
    """

    if isinstance(raw, str):
        return raw
    if isinstance(raw, (list, tuple)):
        parts = []
        for block in raw:
            if isinstance(block, dict):
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return "\n".join(p for p in parts if p)
    return str(raw)


def _max_tool_calls() -> int:
    """Per-turn tool-call cap; falls back to the documented default."""

    try:
        return get_settings().max_tool_calls_per_turn
    except Exception:  # no .env in a bare test/CI environment
        return 4


def _context_budget() -> int:
    try:
        return get_settings().context_token_budget
    except Exception:
        return 6000


# ---------------------------------------------------------------------------
# product_cards extraction — tool JSON in, UI payload out. No model text.
# ---------------------------------------------------------------------------
def _to_rupees(value: Any) -> str | None:
    """Normalise a price value to a major-unit (rupee) decimal string.

    The two Storefront MCP tools disagree on units, but the JSON *type* carries
    the convention (verified against the live store, Stage 4): ``search_catalog``
    sends numbers in MINOR units (39900 == ₹399), ``get_product_details`` sends
    strings already in rupees ("399.0").
    """

    if value is None:
        return None
    try:
        if isinstance(value, str):
            return f"{float(value):.2f}"
        return f"{float(value) / 100:.2f}"
    except (TypeError, ValueError):
        return None


def _money(node: Any, currency_fallback: str | None) -> tuple[str | None, str | None]:
    """Pull (amount, currency) out of a price node in any shape the MCP uses.

    Handles ``{"amount": 39900, "currency": "INR"}`` (live search), a bare
    scalar (legacy flat shape), and strings ("399.0", live details).
    """

    if isinstance(node, dict):
        return _to_rupees(node.get("amount")), node.get("currency") or currency_fallback
    return _to_rupees(node), currency_fallback


def _variant_entry(variant: dict) -> dict | None:
    """Map one tool-JSON variant to the card's ``{id, title, available}`` shape."""

    variant_id = variant.get("id") or variant.get("variant_id")
    if not variant_id:
        return None

    availability = variant.get("availability")
    if isinstance(availability, dict):  # live search_catalog nests it
        available = bool(availability.get("available", True))
    else:
        available = bool(variant.get("available", True))

    return {"id": str(variant_id), "title": str(variant.get("title", "")), "available": available}


def _card_from_search(product: dict) -> dict | None:
    """Build a product card from one ``search_catalog`` result entry."""

    product_id = product.get("id") or product.get("product_id")
    if not product_id:
        return None

    price_range = product.get("price_range") or {}
    amount, currency = _money(price_range.get("min"), price_range.get("currency"))

    variants = [v for v in map(_variant_entry, product.get("variants") or []) if v]

    # Live search results carry no product-level image; fall back to the first
    # variant's media entry.
    image_url = product.get("image_url") or ""
    if not image_url:
        for variant in product.get("variants") or []:
            for media in variant.get("media") or []:
                if media.get("url"):
                    image_url = media["url"]
                    break
            if image_url:
                break

    return {
        "id": str(product_id),
        "title": str(product.get("title", "")),
        "url": str(product.get("url", "")),
        "image_url": str(image_url),
        "price": {"amount": amount or "", "currency": currency or "INR"},
        "variants": variants,
    }


def _card_from_details(payload: dict) -> dict | None:
    """Build a product card from a ``get_product_details`` response."""

    product = payload.get("product") if isinstance(payload.get("product"), dict) else payload
    product_id = product.get("product_id") or product.get("id")
    if not product_id:
        return None

    price_range = product.get("price_range") or {}
    amount, currency = _money(price_range.get("min"), price_range.get("currency"))

    raw_variants = product.get("variants")
    if not raw_variants:
        selected = product.get("selectedOrFirstAvailableVariant")
        raw_variants = [selected] if isinstance(selected, dict) else []
    variants = [v for v in map(_variant_entry, raw_variants) if v]

    image_url = product.get("image_url") or ""
    if not image_url:
        images = product.get("images") or product.get("image_urls") or []
        first = images[0] if images else None
        image_url = first.get("url", "") if isinstance(first, dict) else (first or "")

    return {
        "id": str(product_id),
        "title": str(product.get("title", "")),
        "url": str(product.get("url", "")),
        "image_url": str(image_url),
        "price": {"amount": amount or "", "currency": currency or "INR"},
        "variants": variants,
    }


def _merge_cards(old: dict, new: dict) -> dict:
    """Refine an existing card with a later result for the same product.

    Scalar fields: the newer non-empty value wins (a details call has the
    better image/price). Variants: union keyed by variant id — a details call
    returns only the selected variant, and dropping the others would strip
    variant ids that Stage 5 cart resolution needs from ``product_context``.
    """

    merged = dict(old)
    for key in ("title", "url", "image_url"):
        if new.get(key):
            merged[key] = new[key]
    if new.get("price", {}).get("amount"):
        merged["price"] = new["price"]

    new_by_id = {v["id"]: v for v in new.get("variants", [])}
    merged["variants"] = [
        new_by_id.pop(v["id"], v) for v in old.get("variants", [])
    ] + list(new_by_id.values())
    return merged


def build_product_cards(tool_results: list[tuple[str, str]]) -> dict:
    """Assemble the ``product_cards`` payload from this turn's raw tool JSON.

    ``tool_results`` is ``[(tool_name, raw_json_string), ...]`` in call order.
    Cards are de-duplicated by product id (a details call refines the earlier
    search entry via :func:`_merge_cards`) and hard-capped at
    :data:`MAX_PRODUCT_CARDS`.
    """

    cards: dict[str, dict] = {}

    def _add(card: dict | None) -> None:
        if card:
            existing = cards.get(card["id"])
            cards[card["id"]] = _merge_cards(existing, card) if existing else card

    for tool_name, raw in tool_results:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.debug("Skipping non-JSON result from %s", tool_name)
            continue
        if not isinstance(payload, dict):
            continue

        if tool_name == "search_catalog":
            for product in payload.get("products") or []:
                _add(_card_from_search(product))
        elif tool_name == "get_product_details":
            _add(_card_from_details(payload))

    return {"products": list(cards.values())[:MAX_PRODUCT_CARDS]}


def _product_context_from_cards(cards: dict) -> list[dict]:
    """Reduce cards to the grounding references kept in graph state.

    Carries ``price`` and per-variant titles in addition to the bare
    ``variant_ids`` (Stage 4): the Cart agent reads ``product_context`` to
    restate the exact line — title, variant, and price — when it proposes an
    ``update_cart``. ``variant_ids`` is preserved unchanged for back-compat.
    """

    return [
        {
            "id": card["id"],
            "title": card["title"],
            "url": card["url"],
            "price": card.get("price", {}),
            "variant_ids": [v["id"] for v in card["variants"]],
            "variants": [
                {"id": v["id"], "title": v.get("title", "")} for v in card["variants"]
            ],
        }
        for card in cards["products"]
    ]


# ---------------------------------------------------------------------------
# The node
# ---------------------------------------------------------------------------
def make_stylist_node(tools: list, llm: Any | None = None):
    """Build the Stylist node over the agent's scoped tools.

    Args:
        tools: The stylist's scope from ``load_scoped_tools()`` —
            search_catalog and get_product_details.
        llm: Test seam; defaults to a fresh ``FallbackChat(temperature=0.3)``
            per turn so the fallback_used flag is per-turn accurate.
    """

    tools_by_name = {t.name: t for t in tools}

    async def stylist_node(state: VastraState) -> dict:
        chat = llm if llm is not None else FallbackChat(temperature=0.3)
        if tools:
            chat = chat.bind_tools(tools)

        profile = state.get("buyer_profile") or {}
        system = SystemMessage(
            content=STYLIST_PROMPT.replace(BUYER_PROFILE_MARKER, json.dumps(profile))
        )
        messages: list = trim_messages([system, *state["messages"]], _context_budget())

        cap = _max_tool_calls()
        executed = 0
        tool_results: list[tuple[str, str]] = []

        response = await chat.ainvoke(messages)
        while getattr(response, "tool_calls", None) and executed < cap:
            messages.append(response)
            for call in response.tool_calls:
                name = call.get("name", "")
                if executed >= cap:
                    content = _BUDGET_EXHAUSTED_MSG
                else:
                    executed += 1
                    content = await _run_tool(tools_by_name, name, call.get("args") or {}, tool_results)
                messages.append(
                    ToolMessage(content=content, tool_call_id=call.get("id", ""), name=name)
                )
            response = await chat.ainvoke(messages)

        if getattr(response, "tool_calls", None):
            # Cap reached but the model asked for more tools: answer the dangling
            # calls (the provider API requires it) and demand a final text reply.
            messages.append(response)
            for call in response.tool_calls:
                messages.append(
                    ToolMessage(
                        content=_BUDGET_EXHAUSTED_MSG,
                        tool_call_id=call.get("id", ""),
                        name=call.get("name", ""),
                    )
                )
            response = await chat.ainvoke(messages)

        product_cards = build_product_cards(tool_results)

        text = _message_text(response).strip()
        if not text:
            text = _FALLBACK_WITH_PRODUCTS if product_cards["products"] else _FALLBACK_NO_PRODUCTS

        # Fresh message: never let a dangling tool_calls list reach the
        # checkpointer, and carry the structured payload with the message.
        final = AIMessage(content=text, additional_kwargs={"product_cards": product_cards})

        update: dict = {
            "messages": [final],
            "fallback_used": bool(getattr(chat, "fallback_used", False)),
        }
        if product_cards["products"]:
            update["product_context"] = _product_context_from_cards(product_cards)
        return update

    return stylist_node


async def _run_tool(
    tools_by_name: dict[str, Any],
    name: str,
    args: dict,
    tool_results: list[tuple[str, str]],
) -> str:
    """Execute one tool call; collect the raw result and return the fenced one."""

    tool = tools_by_name.get(name)
    if tool is None:
        logger.warning("Stylist requested unknown tool %r", name)
        return f"Error: tool '{name}' is not available."

    try:
        raw = await tool.ainvoke(args)
    except Exception as exc:  # MCP/network failure — tell the model, keep the turn alive
        logger.warning("Tool %s failed: %s", name, exc)
        return f"Error calling {name}: {type(exc).__name__}"

    raw_text = _content_to_text(raw)
    tool_results.append((name, raw_text))
    return sanitize_tool_output(raw_text)
