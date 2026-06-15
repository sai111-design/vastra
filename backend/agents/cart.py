"""Cart specialist — interrupt-gated cart writes.

``make_cart_node(tools)`` returns an async LangGraph node that runs a bounded
ReAct loop over the cart-scoped MCP tools (get_cart, update_cart). The safety
invariant (Agent/rules.md): ``update_cart`` is NEVER executed without an
explicit, approved confirmation. That gate is a LangGraph ``interrupt()``:

1. The model decides to mutate the cart and emits an ``update_cart`` tool call.
2. The node does NOT run the tool. It builds a ``pending`` action restating the
   exact line (title, variant, qty, price, resolved from ``product_context``)
   and calls ``interrupt(pending)``. The graph pauses; the API layer (Stage 6)
   surfaces ``pending`` as the ``confirm_request`` SSE event.
3. The caller resumes with ``Command(resume={"approved": bool})``. LangGraph
   re-executes the node from the top, and this time ``interrupt`` *returns* the
   resume value instead of pausing. Only on approval does the node invoke
   ``update_cart``.

Because of that re-execution, everything before the interrupt must be
deterministic — the model runs at temperature 0 and the only durable side
effect (the tool call) happens strictly after approval.

Reads ("show me my cart") call get_cart, emit a ``cart_update`` payload, and
never interrupt. Like the Stylist's ``product_cards``, the ``cart_update``
payload is built ONLY from the tool's JSON response, never from model text.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.types import interrupt

from backend.agents.prompts import (
    BUYER_PROFILE_MARKER,
    CART_PROMPT,
    PRODUCT_CONTEXT_MARKER,
)
from backend.agents.state import VastraState
from backend.agents.stylist import _content_to_text, _to_rupees
from backend.agents.supervisor import _message_text, trim_messages
from backend.config import get_settings
from backend.llm.fallback import FallbackChat
from backend.mcp.sanitize import sanitize_tool_output

logger = logging.getLogger(__name__)

# Read-only vs mutating cart tools.
_MUTATING_TOOL = "update_cart"
_READ_TOOL = "get_cart"

_BUDGET_EXHAUSTED_MSG = (
    "Tool-call budget for this turn is exhausted. Answer the buyer now using "
    "only the tool data you already received."
)
_CART_UNCHANGED_MSG = "No problem — your cart is unchanged."
_TOOL_FAILED_MSG = (
    "Sorry, I couldn't update your cart just now — please try again in a moment."
)
_FALLBACK_CART_MSG = "Here's your cart."
_FALLBACK_NO_CART_MSG = "What would you like to do with your cart?"


def _max_tool_calls() -> int:
    try:
        return get_settings().max_tool_calls_per_turn
    except Exception:  # no .env in a bare test/CI environment
        return 4


def _context_budget() -> int:
    try:
        return get_settings().context_token_budget
    except Exception:
        return 6000


def _backoff_seconds(attempt: int) -> float:
    """Exponential backoff (seconds) for the one cart-tool retry."""

    return float(2**attempt)


def _bind_cart_id(args: dict, cart_id: str | None) -> None:
    """Bind the authoritative cart_id into tool args, or omit it for a new cart.

    The model never owns the cart_id (it isn't in the messages it sees), so any
    model-supplied value is dropped. When the session has a cart we inject the
    real id; when it doesn't, we leave cart_id absent so ``update_cart`` creates
    one (live Storefront MCP behaviour).
    """

    if cart_id:
        args["cart_id"] = cart_id
    else:
        args.pop("cart_id", None)


# ---------------------------------------------------------------------------
# Proposed-line resolution — what the confirmation restates
# ---------------------------------------------------------------------------
def _extract_add_target(args: dict) -> tuple[str | None, int]:
    """Pull (variant_id, quantity) out of an update_cart argument blob.

    Handles the live ``add_items: [{variant_id, quantity}]`` shape plus a few
    near-equivalents the model might emit; falls back to remove/flat shapes so
    the proposal is still meaningful for a non-add mutation.
    """

    for key in ("add_items", "update_items", "lines"):
        items = args.get(key)
        if isinstance(items, list) and items and isinstance(items[0], dict):
            first = items[0]
            vid = (
                first.get("variant_id")
                or first.get("merchandiseId")
                or first.get("id")
                or first.get("line_id")
            )
            qty = first.get("quantity", 1)
            return (str(vid) if vid else None, _as_qty(qty))

    removes = args.get("remove_line_ids")
    if isinstance(removes, list) and removes:
        return (str(removes[0]), 0)

    vid = args.get("variant_id") or args.get("merchandiseId")
    return (str(vid) if vid else None, _as_qty(args.get("quantity", 1)))


def _as_qty(value: Any) -> int:
    if isinstance(value, bool):
        return 1
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 1


def _resolve_line(args: dict, product_context: list[dict]) -> dict:
    """Resolve the human-facing line details from grounded product_context.

    Returns ``{variant_id, quantity, variant_title, title, price}``. Title,
    variant title, and price come from ``product_context`` (set by the Stylist)
    so the confirmation restates real catalog facts, never model invention.
    """

    variant_id, quantity = _extract_add_target(args)
    title = ""
    variant_title = ""
    price: Any = None

    for product in product_context or []:
        variant_ids = [str(v) for v in product.get("variant_ids") or []]
        matched_variant = next(
            (
                v
                for v in product.get("variants") or []
                if str(v.get("id")) == str(variant_id)
            ),
            None,
        )
        if matched_variant is not None or (variant_id and str(variant_id) in variant_ids):
            title = str(product.get("title") or "")
            price = product.get("price")
            if matched_variant is not None:
                variant_title = str(matched_variant.get("title") or "")
            break

    return {
        "variant_id": variant_id,
        "quantity": quantity,
        "variant_title": variant_title,
        "title": title,
        "price": price,
    }


def _summary(info: dict) -> str:
    """Build the one-line confirmation restating the exact proposed line."""

    title = info.get("title") or "this item"
    variant_title = info.get("variant_title") or ""
    qty = info.get("quantity") if info.get("quantity") is not None else 1
    price = info.get("price")
    amount = price.get("amount") if isinstance(price, dict) else (
        price if isinstance(price, str) else None
    )

    summary = f"Add {title}"
    if variant_title:
        summary += f" ({variant_title})"
    if amount:
        summary += f" — ₹{amount}"
    summary += f" × {qty} to your cart?"
    return summary


def _build_pending(args: dict, product_context: list[dict]) -> dict:
    """Assemble the interrupt payload (the future ``confirm_request`` event)."""

    info = _resolve_line(args, product_context)
    return {
        "action_id": uuid4().hex[:8],
        "summary": _summary(info),
        "line": {
            "variant_id": info["variant_id"],
            "quantity": info["quantity"],
            "title": info["title"],
            "price": info["price"],
        },
    }


# ---------------------------------------------------------------------------
# cart_update payload — built from tool JSON only, never model text
# ---------------------------------------------------------------------------
def cart_update_from_json(raw: str) -> dict | None:
    """Build the ``cart_update`` SSE payload from a cart tool's JSON response.

    Returns ``None`` if the response is not parseable as a cart object — the
    node then refuses to claim a cart change. Cart prices arrive in minor units
    (paise) and are normalised to major-unit rupee strings.
    """

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if not data.get("cart_id") and not data.get("lines"):
        return None

    lines = []
    for line in data.get("lines") or []:
        if not isinstance(line, dict):
            continue
        lines.append(
            {
                "line_id": str(line.get("line_id") or ""),
                "variant_id": str(line.get("variant_id") or ""),
                "title": str(line.get("title") or ""),
                "quantity": line.get("quantity") or 0,
                "unit_price": _to_rupees(line.get("unit_price")) or "",
                "line_price": _to_rupees(line.get("line_price")) or "",
            }
        )

    return {
        "cart_id": str(data.get("cart_id") or ""),
        "checkout_url": str(data.get("checkout_url") or ""),
        "currency": str(data.get("currency") or "INR"),
        "subtotal": _to_rupees(data.get("subtotal")) or "",
        "total_quantity": data.get("total_quantity") or 0,
        "lines": lines,
    }


# ---------------------------------------------------------------------------
# Tool execution with one retry
# ---------------------------------------------------------------------------
async def _invoke_with_retry(tool: Any, args: dict, *, retries: int = 1) -> Any:
    """Invoke a cart tool, retrying once with exponential backoff on error."""

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return await tool.ainvoke(args)
        except Exception as exc:  # noqa: BLE001 - retry then surface honestly
            last_exc = exc
            if attempt < retries:
                await asyncio.sleep(_backoff_seconds(attempt))
    assert last_exc is not None
    raise last_exc


async def _run_cart_tool(
    tools_by_name: dict[str, Any], name: str, args: dict
) -> tuple[str, bool]:
    """Run one cart tool. Returns ``(text, failed)``.

    ``text`` is the flattened tool output on success or an honest error string
    on failure; ``failed`` flags the latter so the node never pretends success.
    """

    tool = tools_by_name.get(name)
    if tool is None:
        return (f"Error: tool '{name}' is not available.", True)
    try:
        raw = await _invoke_with_retry(tool, args)
    except Exception as exc:  # noqa: BLE001 - already retried once
        logger.warning("Cart tool %s failed after retry: %s", name, exc)
        return (f"Error calling {name}: {type(exc).__name__}", True)
    return (_content_to_text(raw), False)


# ---------------------------------------------------------------------------
# The node
# ---------------------------------------------------------------------------
def make_cart_node(tools: list, llm: Any | None = None):
    """Build the Cart node over the agent's scoped tools (get_cart, update_cart).

    Args:
        tools: The cart scope from ``load_scoped_tools()``.
        llm: Test seam; defaults to a fresh ``FallbackChat(temperature=0)`` per
            turn. Must be deterministic across re-execution (see module docs).
    """

    tools_by_name = {t.name: t for t in tools}

    async def cart_node(state: VastraState) -> dict:
        chat = llm if llm is not None else FallbackChat(temperature=0.0)
        if tools:
            chat = chat.bind_tools(tools)

        profile = state.get("buyer_profile") or {}
        product_context = state.get("product_context") or []
        system = SystemMessage(
            content=CART_PROMPT.replace(
                BUYER_PROFILE_MARKER, json.dumps(profile)
            ).replace(PRODUCT_CONTEXT_MARKER, json.dumps(product_context))
        )
        messages: list = trim_messages([system, *state["messages"]], _context_budget())

        cart_id = state.get("cart_id")
        cap = _max_tool_calls()
        executed = 0
        cart_update: dict | None = None
        tool_failed = False

        response = await chat.ainvoke(messages)
        while getattr(response, "tool_calls", None) and executed < cap:
            messages.append(response)
            for call in response.tool_calls:
                name = call.get("name", "")
                args = dict(call.get("args") or {})
                call_id = call.get("id", "")

                if executed >= cap:
                    messages.append(
                        ToolMessage(content=_BUDGET_EXHAUSTED_MSG, tool_call_id=call_id, name=name)
                    )
                    continue

                if name == _MUTATING_TOOL:
                    # SAFETY GATE — propose the exact line, then pause for approval.
                    pending = _build_pending(args, product_context)
                    decision = interrupt(pending)
                    if not isinstance(decision, dict) or not decision.get("approved"):
                        # Denied (or malformed resume): never touch the cart.
                        return {
                            "messages": [AIMessage(content=_CART_UNCHANGED_MSG)],
                            "pending_action": None,
                        }
                    # Approved: bind the authoritative cart_id (or omit it so the
                    # tool creates a cart) — never trust a model-supplied id.
                    _bind_cart_id(args, cart_id)
                    executed += 1
                    text, failed = await _run_cart_tool(tools_by_name, name, args)
                    if failed:
                        tool_failed = True
                        messages.append(ToolMessage(content=text, tool_call_id=call_id, name=name))
                        continue
                    payload = cart_update_from_json(text)
                    if payload:
                        cart_update = payload
                    messages.append(
                        ToolMessage(content=sanitize_tool_output(text), tool_call_id=call_id, name=name)
                    )

                elif name == _READ_TOOL:
                    # Read-only: no confirmation needed.
                    _bind_cart_id(args, cart_id)
                    executed += 1
                    text, failed = await _run_cart_tool(tools_by_name, name, args)
                    if failed:
                        tool_failed = True
                        messages.append(ToolMessage(content=text, tool_call_id=call_id, name=name))
                        continue
                    payload = cart_update_from_json(text)
                    if payload:
                        cart_update = payload
                    messages.append(
                        ToolMessage(content=sanitize_tool_output(text), tool_call_id=call_id, name=name)
                    )

                else:
                    messages.append(
                        ToolMessage(
                            content=f"Error: tool '{name}' is not available.",
                            tool_call_id=call_id,
                            name=name,
                        )
                    )

            response = await chat.ainvoke(messages)

        if getattr(response, "tool_calls", None):
            # Cap reached with more tools requested: answer the danglers (never
            # by executing them) and force a final text reply.
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

        text = _message_text(response).strip()
        if not text:
            text = _FALLBACK_CART_MSG if cart_update else _FALLBACK_NO_CART_MSG
        if tool_failed and cart_update is None:
            text = _TOOL_FAILED_MSG

        final = AIMessage(
            content=text,
            additional_kwargs=({"cart_update": cart_update} if cart_update else {}),
        )
        update: dict = {
            "messages": [final],
            "fallback_used": bool(getattr(chat, "fallback_used", False)),
            "pending_action": None,
        }
        if cart_update:
            update["cart_snapshot"] = cart_update
            if cart_update.get("cart_id"):
                update["cart_id"] = cart_update["cart_id"]
        return update

    return cart_node
