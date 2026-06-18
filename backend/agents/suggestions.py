"""Post-turn suggestion generator — 3–4 tappable quick-reply chips.

Runs *after* the main graph turn finishes but *before* the ``done`` SSE event is
emitted, so the chips arrive in the same payload the frontend already reads to
mark the turn complete. The call hits the small (8B Instant) model at
temperature 0 for fast, deterministic-ish output.

Contract: ``generate_suggestions`` returns at most 4 short strings, and never
raises. Any model error, parse error, or schema mismatch yields ``[]`` so the
turn is never blocked — the frontend simply renders nothing.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.supervisor import _message_text
from backend.llm.fallback import FallbackChat

logger = logging.getLogger(__name__)

MAX_SUGGESTIONS = 4
MAX_SUGGESTION_CHARS = 60

SUGGESTION_SYSTEM = """You are a shopping assistant suggestion engine.
Given the last assistant message and buyer context, generate 3–4 short, tappable
quick-reply suggestions the buyer might naturally send next.

Rules:
- Each suggestion: 2–6 words max, natural language, no punctuation at end
- Mix action suggestions (Add to cart, Show more) and refinement suggestions (Under ₹500, In black)
- If the last turn showed products: include at least one "Add [product name]" suggestion
- If the last turn answered a policy question: include "What else can I help with"
- Never duplicate the last user message
- Output ONLY a JSON array of strings. No preamble, no markdown fences.
  Example: ["Show me in blue", "Under ₹500 only", "Add the first one", "Any dresses instead"]
"""


def _parse_suggestions(raw: str) -> list[str]:
    """Extract a JSON list of strings from the model's reply, tolerantly."""

    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()

    data: Any = None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except (json.JSONDecodeError, TypeError):
                data = None

    if not isinstance(data, list):
        return []

    cleaned: list[str] = []
    for item in data:
        if not isinstance(item, str):
            continue
        s = item.strip().rstrip(".!?,")
        if 0 < len(s) <= MAX_SUGGESTION_CHARS:
            cleaned.append(s)
        if len(cleaned) >= MAX_SUGGESTIONS:
            break
    return cleaned


async def generate_suggestions(
    last_assistant_message: str,
    last_route: str,
    product_context: list[dict] | None,
    llm: Any | None = None,
) -> list[str]:
    """Return up to 4 short follow-up chips for the buyer's next turn.

    Args:
        last_assistant_message: Final reply text the buyer just saw.
        last_route: Supervisor route for the turn (``stylist``/``cart``/...).
        product_context: Latest grounded product list (titles are sampled).
        llm: Test seam; defaults to ``FallbackChat(temperature=0.0, small=True)``.

    Returns ``[]`` on any failure — generation must never break a turn.
    """

    if not last_assistant_message:
        return []

    titles = []
    for p in (product_context or [])[:3]:
        title = p.get("title") if isinstance(p, dict) else None
        if title:
            titles.append(str(title))
    context_line = f"Products shown: {', '.join(titles)}" if titles else ""

    user_content = (
        f"Last assistant message: {last_assistant_message[:400]}\n"
        f"Route: {last_route or 'respond'}\n"
        f"{context_line}\n\n"
        "Generate suggestions:"
    )

    chat = llm if llm is not None else FallbackChat(temperature=0.0, small=True)
    try:
        response = await chat.ainvoke([
            SystemMessage(content=SUGGESTION_SYSTEM),
            HumanMessage(content=user_content),
        ])
    except Exception as exc:  # noqa: BLE001 - suggestions must never break a turn
        logger.warning("Suggestion generation failed: %s", exc)
        return []

    return _parse_suggestions(_message_text(response))
