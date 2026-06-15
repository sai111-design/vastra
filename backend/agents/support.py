"""Support specialist — policy/FAQ answers grounded in the store's published text.

``make_support_node(tools)`` returns an async LangGraph node that runs a
bounded ReAct loop over the single support-scoped tool
(``search_shop_policies_and_faqs``). The model calls the tool with the buyer's
question, then composes an answer that cites the policy section it used.

Grounding contract (Agent/rules.md; enforced as a hard prompt rule and tested
in the Stage 8 evals): the agent answers ONLY from tool results and never
invents policy. When the tool returns nothing relevant, the agent says the
store has no published policy on that topic rather than guessing.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from backend.agents.prompts import BUYER_PROFILE_MARKER, SUPPORT_PROMPT
from backend.agents.state import VastraState
from backend.agents.stylist import _content_to_text
from backend.agents.supervisor import _message_text, trim_messages
from backend.config import get_settings
from backend.llm.fallback import FallbackChat
from backend.mcp.sanitize import sanitize_tool_output

logger = logging.getLogger(__name__)

_BUDGET_EXHAUSTED_MSG = (
    "Tool-call budget for this turn is exhausted. Answer the buyer now using "
    "only the policy data you already received."
)
# Honest fallback when the model returns no prose — makes no policy claim.
_FALLBACK_SUPPORT_MSG = (
    "I couldn't find a published store policy on that — please reach out to the "
    "store directly and they'll be able to help."
)


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


async def _run_support_tool(tools_by_name: dict[str, Any], name: str, args: dict) -> str:
    """Run the policy tool; return the fenced result or an honest error string."""

    tool = tools_by_name.get(name)
    if tool is None:
        # Support has only the policy tool — anything else can't ground an answer.
        return f"Error: tool '{name}' is not available."
    try:
        raw = await tool.ainvoke(args)
    except Exception as exc:  # noqa: BLE001 - keep the turn alive, tell the model
        logger.warning("Support tool %s failed: %s", name, exc)
        return f"Error calling {name}: {type(exc).__name__}"
    return sanitize_tool_output(_content_to_text(raw))


def make_support_node(tools: list, llm: Any | None = None):
    """Build the Support node over the policy/FAQ tool.

    Args:
        tools: The support scope from ``load_scoped_tools()`` —
            ``search_shop_policies_and_faqs``.
        llm: Test seam; defaults to a fresh ``FallbackChat(temperature=0)``.
    """

    tools_by_name = {t.name: t for t in tools}

    async def support_node(state: VastraState) -> dict:
        chat = llm if llm is not None else FallbackChat(temperature=0.0)
        if tools:
            chat = chat.bind_tools(tools)

        profile = state.get("buyer_profile") or {}
        system = SystemMessage(
            content=SUPPORT_PROMPT.replace(BUYER_PROFILE_MARKER, json.dumps(profile))
        )
        messages: list = trim_messages([system, *state["messages"]], _context_budget())

        cap = _max_tool_calls()
        executed = 0

        response = await chat.ainvoke(messages)
        while getattr(response, "tool_calls", None) and executed < cap:
            messages.append(response)
            for call in response.tool_calls:
                name = call.get("name", "")
                args = call.get("args") or {}
                call_id = call.get("id", "")
                if executed >= cap:
                    content = _BUDGET_EXHAUSTED_MSG
                else:
                    executed += 1
                    content = await _run_support_tool(tools_by_name, name, args)
                messages.append(ToolMessage(content=content, tool_call_id=call_id, name=name))
            response = await chat.ainvoke(messages)

        if getattr(response, "tool_calls", None):
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

        text = _message_text(response).strip() or _FALLBACK_SUPPORT_MSG
        final = AIMessage(content=text)
        return {
            "messages": [final],
            "fallback_used": bool(getattr(chat, "fallback_used", False)),
        }

    return support_node
