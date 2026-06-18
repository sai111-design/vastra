"""Supervisor router node — classifies each buyer turn into a route.

The supervisor is the graph's entry node. It reads the (trimmed) conversation
plus the buyer profile, asks the LLM for a one-field JSON classification, and
writes ``route`` into state for the conditional edge to dispatch on. It never
calls tools and never speaks to the buyer.

Failure policy: any malformed or unparsable model response defaults to
``"stylist"`` — a wrong discovery turn is recoverable, a dropped turn is not.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import SystemMessage

from backend.agents.prompts import BUYER_PROFILE_MARKER, SUPERVISOR_PROMPT
from backend.agents.state import VastraState
from backend.config import get_settings
from backend.llm.fallback import FallbackChat

logger = logging.getLogger(__name__)

ROUTES: frozenset[str] = frozenset(
    {"stylist", "cart", "support", "respond", "complete_look"}
)
DEFAULT_ROUTE = "stylist"

# Crude but provider-independent token estimate: ~4 characters per token, plus
# a small per-message overhead for role/format tokens.
_CHARS_PER_TOKEN = 4
_PER_MESSAGE_OVERHEAD = 8

_llm: FallbackChat | None = None


def _get_llm() -> FallbackChat:
    """Lazily build the shared router model (patched out in tests).

    NB: ``fallback_used`` on this shared instance is sticky across turns, so
    the supervisor never reads it — the stylist's fresh per-turn instance is
    the only consumer of that flag.
    """

    global _llm
    if _llm is None:
        _llm = FallbackChat(temperature=0.0)
    return _llm


def _context_budget() -> int:
    """The per-call token budget; falls back to the documented default."""

    try:
        return get_settings().context_token_budget
    except Exception:  # no .env in a bare test/CI environment
        return 6000


def estimate_tokens(message: Any) -> int:
    """Rough token cost of one message (content may be str or a parts list)."""

    content = getattr(message, "content", message)
    return len(str(content)) // _CHARS_PER_TOKEN + _PER_MESSAGE_OVERHEAD


def trim_messages(messages: list, budget: int) -> list:
    """Trim a message list to ~``budget`` tokens, dropping from the middle.

    Keeps a leading ``SystemMessage`` (if present) and as many of the most
    recent messages as fit; the oldest non-system messages go first. The
    newest message is always kept, even if it alone exceeds the budget —
    sending the model a window without the current turn would be worse than
    overshooting.
    """

    if not messages:
        return []

    head: list = []
    rest = messages
    if isinstance(messages[0], SystemMessage):
        head = [messages[0]]
        rest = messages[1:]

    used = sum(estimate_tokens(m) for m in head)
    kept: list = []
    for message in reversed(rest):
        cost = estimate_tokens(message)
        if kept and used + cost > budget:
            break
        used += cost
        kept.append(message)
    kept.reverse()

    return head + kept


def _message_text(response: Any) -> str:
    """Flatten a model response's content to plain text (Gemini may send parts)."""

    content = getattr(response, "content", response)
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text", "")))
            else:
                parts.append(str(part))
        return "".join(parts)
    return str(content)


def parse_route(text: str) -> str:
    """Extract the route from the model's reply; default to ``stylist``.

    Accepts the requested bare JSON object, but tolerates code fences and
    surrounding prose by falling back to a regex scan for the ``route`` key.
    """

    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", stripped).strip()

    try:
        data = json.loads(stripped)
        route = str(data.get("route", "")).strip().lower()
        if route in ROUTES:
            return route
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass

    match = re.search(r'"route"\s*:\s*"([\w_]+)"', text)
    if match and match.group(1).lower() in ROUTES:
        return match.group(1).lower()

    logger.warning("Supervisor produced no parsable route (%.120r); defaulting to %s", text, DEFAULT_ROUTE)
    return DEFAULT_ROUTE


async def supervisor_node(state: VastraState) -> dict:
    """Classify the latest buyer message and write the route into state."""

    profile = state.get("buyer_profile") or {}
    system = SystemMessage(
        content=SUPERVISOR_PROMPT.replace(BUYER_PROFILE_MARKER, json.dumps(profile))
    )

    window = trim_messages([system, *state["messages"]], _context_budget())
    response = await _get_llm().ainvoke(window)
    route = parse_route(_message_text(response))

    return {"route": route, "turn_count": state.get("turn_count", 0) + 1}
