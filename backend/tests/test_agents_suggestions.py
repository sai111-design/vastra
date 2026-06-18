"""Suggestion generator tests — fully offline (canned 8B-model output).

These pin the wire contract for the ``done`` event's ``suggestions`` field: at
most 4 short strings, never raises, robust to JSON fences and stray prose, and
empty when the model errors or returns a non-list. The chip-quality judgement
itself is exercised live on the demo.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from backend.agents.suggestions import MAX_SUGGESTIONS, generate_suggestions


class _ScriptedLLM:
    """Minimal canned-output stand-in for ``FallbackChat(small=True)``."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list = []

    async def ainvoke(self, messages, **kwargs):  # noqa: ANN001
        self.calls.append(list(messages))
        return AIMessage(content=self._text)


class _BoomLLM:
    async def ainvoke(self, messages, **kwargs):  # noqa: ANN001
        raise RuntimeError("model down")


async def test_returns_parsed_list():
    llm = _ScriptedLLM(
        '["Show me in blue", "Under 500 only", "Add the first one", "Any dresses instead"]'
    )
    out = await generate_suggestions(
        "Here are some black tees.",
        "stylist",
        [{"title": "Oversized black tee"}],
        llm=llm,
    )
    assert out == [
        "Show me in blue",
        "Under 500 only",
        "Add the first one",
        "Any dresses instead",
    ]


async def test_caps_at_four_suggestions():
    llm = _ScriptedLLM('["a","b","c","d","e","f"]')
    out = await generate_suggestions("reply", "stylist", [], llm=llm)
    assert len(out) == MAX_SUGGESTIONS
    assert out == ["a", "b", "c", "d"]


async def test_tolerates_code_fences():
    llm = _ScriptedLLM('```json\n["Show more", "In black"]\n```')
    out = await generate_suggestions("reply", "stylist", [], llm=llm)
    assert out == ["Show more", "In black"]


async def test_strips_trailing_punctuation():
    llm = _ScriptedLLM('["Show me more.", "Under 500!"]')
    out = await generate_suggestions("reply", "stylist", [], llm=llm)
    assert out == ["Show me more", "Under 500"]


async def test_drops_oversized_and_non_strings():
    import json as _json
    too_long = "x" * 80
    llm = _ScriptedLLM(_json.dumps(["ok", too_long, 42, "also ok"]))
    out = await generate_suggestions("reply", "stylist", [], llm=llm)
    assert out == ["ok", "also ok"]


async def test_returns_empty_for_garbage_output():
    llm = _ScriptedLLM("I think you should ask for more black tees!")
    out = await generate_suggestions("reply", "stylist", [], llm=llm)
    assert out == []


async def test_returns_empty_when_model_returns_non_list():
    llm = _ScriptedLLM('{"suggestions": ["nope"]}')
    out = await generate_suggestions("reply", "stylist", [], llm=llm)
    assert out == []


async def test_never_raises_on_model_error():
    out = await generate_suggestions("reply", "stylist", [], llm=_BoomLLM())
    assert out == []


async def test_returns_empty_when_no_assistant_message():
    llm = _ScriptedLLM('["should not be called"]')
    out = await generate_suggestions("", "stylist", [], llm=llm)
    assert out == []
    # Optimisation: skip the model call entirely when there's nothing to base chips on.
    assert llm.calls == []


async def test_passes_product_titles_into_prompt():
    llm = _ScriptedLLM('["Add the first one"]')
    await generate_suggestions(
        "Here are some tees.",
        "stylist",
        [{"title": "Black tee"}, {"title": "Blue tee"}, {"title": "Red tee"}],
        llm=llm,
    )
    [system, user] = llm.calls[0]
    assert "Black tee" in user.content
    assert "Blue tee" in user.content
    assert "Red tee" in user.content


async def test_handles_missing_product_titles():
    llm = _ScriptedLLM('["Refine search"]')
    await generate_suggestions(
        "Here are some tees.",
        "stylist",
        [{"id": "p1"}, {"title": ""}],
        llm=llm,
    )
    [_system, user] = llm.calls[0]
    # No "Products shown:" line should be injected when no titles survive.
    assert "Products shown" not in user.content
