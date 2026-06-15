"""Preference Extractor — async buyer-memory builder.

``extract_preferences`` reads the latest buyer message + assistant reply and
returns a *delta* of durable preferences (only the fields the buyer explicitly
stated). It runs on the small (8B) model at temperature 0 and is designed to
run AFTER the buyer-facing response is sent — in the CLI it runs synchronously
post-turn; in the API layer (Stage 6) it runs as a background task. It must
never block or break the turn, so every failure path returns ``{}``.

``merge_profile`` folds a delta into the existing profile (capping
``style_tags`` at :data:`MAX_STYLE_TAGS`) and returns the merged profile to
upsert into ``buyer_profiles``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.prompts import EXTRACTOR_PROMPT
from backend.agents.supervisor import _message_text
from backend.llm.fallback import FallbackChat

logger = logging.getLogger(__name__)

MAX_STYLE_TAGS = 12

# The full extraction schema; every parse starts from these defaults so missing
# keys can never raise and the delta logic has a stable shape to filter.
_SCHEMA_DEFAULTS: dict[str, Any] = {
    "sizes": {},
    "budget_min": None,
    "budget_max": None,
    "style_tags": [],
    "last_category": None,
}


def _parse_extraction(text: str) -> dict:
    """Parse the model's JSON into the full schema, tolerating fences/prose.

    Returns the schema with defaults for anything missing or malformed — never
    raises. Budgets are coerced to ints; sizes/style_tags are type-checked.
    """

    stripped = text.strip()
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

    result = {
        "sizes": {},
        "budget_min": None,
        "budget_max": None,
        "style_tags": [],
        "last_category": None,
    }
    if not isinstance(data, dict):
        return result

    if isinstance(data.get("sizes"), dict):
        result["sizes"] = {str(k): str(v) for k, v in data["sizes"].items() if v}
    for key in ("budget_min", "budget_max"):
        value = data.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            result[key] = int(value)
    if isinstance(data.get("style_tags"), list):
        result["style_tags"] = [str(t).strip() for t in data["style_tags"] if str(t).strip()]
    last_category = data.get("last_category")
    if isinstance(last_category, str) and last_category.strip():
        result["last_category"] = last_category.strip()

    return result


def _delta(parsed: dict) -> dict:
    """Reduce a parsed schema to only the non-empty fields the buyer stated."""

    delta: dict = {}
    if parsed.get("sizes"):
        delta["sizes"] = parsed["sizes"]
    if parsed.get("budget_min") is not None:
        delta["budget_min"] = parsed["budget_min"]
    if parsed.get("budget_max") is not None:
        delta["budget_max"] = parsed["budget_max"]
    if parsed.get("style_tags"):
        delta["style_tags"] = parsed["style_tags"]
    if parsed.get("last_category"):
        delta["last_category"] = parsed["last_category"]
    return delta


async def extract_preferences(
    last_user_msg: str, last_assistant_msg: str, *, llm: Any | None = None
) -> dict:
    """Extract a preference delta from the latest exchange.

    Args:
        last_user_msg: The buyer's most recent message.
        last_assistant_msg: The assistant's most recent reply.
        llm: Test seam; defaults to ``FallbackChat(temperature=0, small=True)``
            (the 8B model).

    Returns:
        A delta dict containing only the non-null fields the buyer explicitly
        stated, e.g. ``{"sizes": {"top": "L"}}`` or ``{}`` if nothing stated.
        Never raises — any error yields ``{}`` so the turn is never blocked.
    """

    chat = llm if llm is not None else FallbackChat(temperature=0.0, small=True)
    messages = [
        SystemMessage(content=EXTRACTOR_PROMPT),
        HumanMessage(
            content=(
                f"Buyer's latest message:\n{last_user_msg}\n\n"
                f"Assistant's latest reply:\n{last_assistant_msg}"
            )
        ),
    ]
    try:
        response = await chat.ainvoke(messages)
    except Exception as exc:  # noqa: BLE001 - extraction must never break a turn
        logger.warning("Preference extraction failed: %s", exc)
        return {}
    return _delta(_parse_extraction(_message_text(response)))


def merge_profile(existing: dict, delta: dict) -> dict:
    """Merge a preference delta into the existing profile.

    Sizes are merged key-by-key (delta wins); budget and last_category are
    overwritten when present; style_tags are unioned (order-preserving, de-
    duplicated) and capped at :data:`MAX_STYLE_TAGS`. Returns a new dict.
    """

    merged = dict(existing or {})

    if "sizes" in delta:
        sizes = dict(merged.get("sizes") or {})
        sizes.update(delta["sizes"])
        merged["sizes"] = sizes

    for key in ("budget_min", "budget_max", "last_category"):
        if key in delta:
            merged[key] = delta[key]

    if "style_tags" in delta:
        tags = list(merged.get("style_tags") or [])
        for tag in delta["style_tags"]:
            if tag not in tags:
                tags.append(tag)
        merged["style_tags"] = tags[:MAX_STYLE_TAGS]

    return merged
