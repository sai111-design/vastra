"""Preference Extractor tests — fully offline (canned small-model output).

These pin the delta contract (only non-null stated fields survive), robust JSON
parsing (fences/prose/garbage), and the profile merge rules (size/budget
overwrite, style_tags union + 12-cap). The model's judgement itself is exercised
live via scripts/cli_chat.py and the Stage 8 evals.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from backend.agents.extractor import MAX_STYLE_TAGS, extract_preferences, merge_profile


class _ScriptedLLM:
    """Minimal canned-output stand-in for FallbackChat(small=True)."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list = []

    @property
    def fallback_used(self) -> bool:
        return False

    async def ainvoke(self, messages, **kwargs):  # noqa: ANN001
        self.calls.append(list(messages))
        return AIMessage(content=self._text)


class _BoomLLM:
    async def ainvoke(self, messages, **kwargs):  # noqa: ANN001
        raise RuntimeError("model down")


_FULL_NULL = (
    '{"sizes": {}, "budget_min": null, "budget_max": null, '
    '"style_tags": [], "last_category": null}'
)


# ---------------------------------------------------------------------------
# extract_preferences — delta extraction
# ---------------------------------------------------------------------------
async def test_extracts_size_to_top():
    llm = _ScriptedLLM(
        '{"sizes": {"top": "L"}, "budget_min": null, "budget_max": null, '
        '"style_tags": [], "last_category": null}'
    )
    delta = await extract_preferences("I'm a size L", "Here are some tops.", llm=llm)
    assert delta == {"sizes": {"top": "L"}}


async def test_extracts_budget_max():
    llm = _ScriptedLLM(
        '{"sizes": {}, "budget_min": null, "budget_max": 800, '
        '"style_tags": [], "last_category": null}'
    )
    delta = await extract_preferences("show me jeans under 800", "Sure!", llm=llm)
    assert delta == {"budget_max": 800}


async def test_extracts_category_and_style():
    llm = _ScriptedLLM(
        '{"sizes": {}, "budget_min": null, "budget_max": null, '
        '"style_tags": ["minimalist"], "last_category": "kurta"}'
    )
    delta = await extract_preferences("a minimalist kurta please", "On it.", llm=llm)
    assert delta == {"style_tags": ["minimalist"], "last_category": "kurta"}


async def test_returns_empty_delta_when_no_preferences():
    llm = _ScriptedLLM(_FULL_NULL)
    delta = await extract_preferences("hello there", "Hi! How can I help?", llm=llm)
    assert delta == {}


async def test_tolerates_code_fences():
    llm = _ScriptedLLM('```json\n{"sizes": {"bottom": "32"}, "budget_max": null}\n```')
    delta = await extract_preferences("I wear 32 in jeans", "Got it.", llm=llm)
    assert delta == {"sizes": {"bottom": "32"}}


async def test_malformed_output_yields_empty_delta():
    llm = _ScriptedLLM("I think the buyer wants a size large, maybe?")
    delta = await extract_preferences("hmm", "ok", llm=llm)
    assert delta == {}


async def test_extraction_never_raises_on_model_error():
    delta = await extract_preferences("anything", "reply", llm=_BoomLLM())
    assert delta == {}


# ---------------------------------------------------------------------------
# merge_profile
# ---------------------------------------------------------------------------
def test_merge_combines_sizes_and_overwrites_budget():
    existing = {"sizes": {"top": "M"}, "budget_max": 1000}
    delta = {"sizes": {"bottom": "32"}, "budget_max": 800}
    merged = merge_profile(existing, delta)
    assert merged["sizes"] == {"top": "M", "bottom": "32"}
    assert merged["budget_max"] == 800


def test_merge_unions_and_dedups_style_tags():
    existing = {"style_tags": ["minimalist", "ethnic"]}
    delta = {"style_tags": ["ethnic", "formal"]}
    merged = merge_profile(existing, delta)
    assert merged["style_tags"] == ["minimalist", "ethnic", "formal"]


def test_merge_caps_style_tags_at_twelve():
    existing = {"style_tags": [f"t{i}" for i in range(10)]}
    delta = {"style_tags": [f"n{i}" for i in range(5)]}
    merged = merge_profile(existing, delta)
    assert len(merged["style_tags"]) == MAX_STYLE_TAGS
    # The 10 existing tags are kept; only the first 2 new ones fit under the cap.
    assert merged["style_tags"][:10] == [f"t{i}" for i in range(10)]
    assert merged["style_tags"][10:] == ["n0", "n1"]


def test_merge_on_empty_existing_profile():
    merged = merge_profile({}, {"sizes": {"top": "L"}, "last_category": "tees"})
    assert merged == {"sizes": {"top": "L"}, "last_category": "tees"}
