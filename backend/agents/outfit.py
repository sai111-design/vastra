"""Outfit Builder specialist — "Complete the Look".

``make_complete_look_node(tools)`` returns an async LangGraph node that runs
when the supervisor classifies a turn as ``complete_look``. It is a two-phase
node:

1. **Plan** — the 70B model is asked, with the buyer's recent
   ``product_context`` and profile, to pick TWO complementary clothing
   categories and a one-line intro. The model returns a small JSON object and
   makes *no* tool calls in this phase.
2. **Search** — the node issues exactly one ``search_catalog`` call per
   planned category (capped at 2 calls, well within
   :data:`MAX_TOOL_CALLS_PER_TURN`). The resulting product cards are merged via
   :func:`backend.agents.stylist.build_product_cards` so the wire shape is
   identical to the Stylist's output, and the payload is tagged
   ``look_completion: True`` plus the intro line.

Grounding contract: same as the Stylist — every price, URL, variant id comes
from the tool data, never from model text. The model only writes the intro
sentence and the two category labels we drop into the search query.

Safety: if there is nothing recent to pair with (no ``product_context``), the
node never calls a tool and replies with a one-liner asking the buyer to point
at something specific. The ``last_cart_action_confirmed`` flag is cleared on
every run so the supervisor's "post-cart" lean fires at most once per add.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from backend.agents.prompts import (
    BUYER_PROFILE_MARKER,
    COMPLETE_LOOK_PLAN_PROMPT,
    PRODUCT_CONTEXT_MARKER,
)
from backend.agents.state import VastraState
from backend.agents.stylist import (
    _content_to_text,
    build_product_cards,
    _product_context_from_cards,
)
from backend.agents.supervisor import _message_text
from backend.llm.fallback import FallbackChat

logger = logging.getLogger(__name__)

# Hard cap on tool calls for this route — one search per planned category.
# Stays comfortably under MAX_TOOL_CALLS_PER_TURN even when budget=3.
MAX_OUTFIT_SEARCHES = 2

_DEFAULT_INTRO = "Here's what I'd pair with it."
_EMPTY_CONTEXT_REPLY = (
    "Tell me which piece you'd like me to pair things with — share the title or "
    "tap one from the shelf and I'll pull a look together."
)
_NO_RESULTS_REPLY = (
    "I looked for pairings but couldn't find a good match in the store right now. "
    "Want me to try a different angle?"
)


def _parse_plan(text: str) -> tuple[str, list[str]]:
    """Pull ``(intro, [cat1, cat2])`` from the planner's JSON reply.

    Tolerates code fences and stray prose. Returns ``("", [])`` on failure so
    the caller can fall back to a no-op reply instead of running junk searches.
    """

    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", stripped).strip()

    data: Any = None
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except (json.JSONDecodeError, TypeError):
                data = None

    if not isinstance(data, dict):
        return "", []

    intro_raw = data.get("intro")
    intro = str(intro_raw).strip() if isinstance(intro_raw, str) else ""
    cats_raw = data.get("categories")
    if not isinstance(cats_raw, list):
        return intro, []

    seen: set[str] = set()
    categories: list[str] = []
    for c in cats_raw:
        if not isinstance(c, str):
            continue
        label = c.strip()
        key = label.lower()
        if not label or key in seen:
            continue
        seen.add(key)
        categories.append(label)
        if len(categories) >= MAX_OUTFIT_SEARCHES:
            break

    return intro, categories


async def _run_search(tool: Any, query: str) -> tuple[str, str] | None:
    """Invoke search_catalog with a category query; return ``(name, raw_text)``.

    Returns ``None`` on tool failure so :func:`build_product_cards` only ever
    sees real JSON from the live tool.
    """

    try:
        raw = await tool.ainvoke({"query": query})
    except Exception as exc:  # noqa: BLE001 - never break the turn on a search miss
        logger.warning("complete_look search %r failed: %s", query, exc)
        return None
    return ("search_catalog", _content_to_text(raw))


def make_complete_look_node(tools: list, llm: Any | None = None):
    """Build the Outfit Builder node over the agent's scoped tools.

    Args:
        tools: ``tools_by_agent["complete_look"]`` — just ``search_catalog``.
        llm: Test seam; defaults to a fresh ``FallbackChat(temperature=0.4)``
            per turn — category recommendation needs a touch of warmth.
    """

    search_tool = next((t for t in tools if t.name == "search_catalog"), None)

    async def complete_look_node(state: VastraState) -> dict:
        product_context = state.get("product_context") or []

        # No grounding to pair against. Fail soft: clear the post-cart flag,
        # explain, and let the buyer redirect.
        if not product_context:
            return {
                "messages": [AIMessage(content=_EMPTY_CONTEXT_REPLY)],
                "last_cart_action_confirmed": False,
            }

        chat = llm if llm is not None else FallbackChat(temperature=0.4)
        profile = state.get("buyer_profile") or {}

        plan_system = SystemMessage(
            content=COMPLETE_LOOK_PLAN_PROMPT
            .replace(BUYER_PROFILE_MARKER, json.dumps(profile))
            .replace(PRODUCT_CONTEXT_MARKER, json.dumps(product_context))
        )
        plan_request = HumanMessage(
            content="Pick two complementary categories and write the intro."
        )

        try:
            plan_response = await chat.ainvoke([plan_system, plan_request])
        except Exception as exc:  # noqa: BLE001 - model error must not break the turn
            logger.warning("complete_look planner failed: %s", exc)
            plan_response = AIMessage(content="")

        intro, categories = _parse_plan(_message_text(plan_response))

        if not categories or search_tool is None:
            return {
                "messages": [AIMessage(content=_NO_RESULTS_REPLY)],
                "last_cart_action_confirmed": False,
                "fallback_used": bool(getattr(chat, "fallback_used", False)),
            }

        # Run the (at most 2) searches in parallel — they're independent.
        results = await asyncio.gather(
            *(_run_search(search_tool, cat) for cat in categories),
            return_exceptions=False,
        )
        tool_results: list[tuple[str, str]] = [r for r in results if r is not None]

        product_cards = build_product_cards(tool_results)
        if not product_cards["products"]:
            return {
                "messages": [AIMessage(content=_NO_RESULTS_REPLY)],
                "last_cart_action_confirmed": False,
                "fallback_used": bool(getattr(chat, "fallback_used", False)),
            }

        # Tag the payload so the frontend knows to render LookCardRow.
        product_cards["look_completion"] = True
        product_cards["look_intro"] = intro or _DEFAULT_INTRO

        # Reply text is the same intro line so the chat bubble matches the
        # look header — pure prose, no product claims (those live in the cards).
        reply_text = intro or _DEFAULT_INTRO
        final = AIMessage(
            content=reply_text,
            additional_kwargs={"product_cards": product_cards},
        )

        return {
            "messages": [final],
            "product_context": _product_context_from_cards(product_cards),
            "last_cart_action_confirmed": False,
            "fallback_used": bool(getattr(chat, "fallback_used", False)),
        }

    return complete_look_node
