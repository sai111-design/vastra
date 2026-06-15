"""Support node tests — policy grounding, fully offline.

The FakeLLM scripts the model's tool-call + answer; the policy tool returns
canned (or empty) results. These tests pin the grounding plumbing: the policy
tool is called with the buyer's question, its text reaches the model, an empty
result surfaces a no-policy answer, and the system prompt actually carries the
anti-invention rule. The full behavioural "never invents policy" guarantee is
verified live in the Stage 8 evals with a real model.
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool

from backend.agents.support import make_support_node
from backend.tests.conftest import FakeLLM


def _state(text: str, **extra) -> dict:
    return {"messages": [HumanMessage(content=text)], "buyer_profile": {}, **extra}


def _tool_call(name: str, args: dict, call_id: str = "p1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def _empty_policy_tool() -> StructuredTool:
    return StructuredTool.from_function(
        func=lambda query, context="": json.dumps({"results": []}),
        name="search_shop_policies_and_faqs",
        description="Search store policies and FAQs.",
    )


# ---------------------------------------------------------------------------
# Grounded answers
# ---------------------------------------------------------------------------
async def test_returns_policy_text_when_matched(fake_scoped_tools):
    fake = FakeLLM(
        responses=[
            _tool_call("search_shop_policies_and_faqs", {"query": "return policy"}),
            AIMessage(
                content="Per our Returns & Exchanges policy, items can be returned within 7 days."
            ),
        ]
    )
    node = make_support_node(fake_scoped_tools["support"], llm=fake)

    result = await node(_state("what's your return policy?"))

    # The policy tool was called and its text reached the model.
    tool_message = next(m for m in fake.calls[1] if isinstance(m, ToolMessage))
    assert tool_message.name == "search_shop_policies_and_faqs"
    assert tool_message.content.startswith("<tool_data>")
    assert "Returns & Exchanges" in tool_message.content
    # The answer cites the named policy section.
    assert "Returns & Exchanges" in result["messages"][-1].content


async def test_says_no_policy_when_results_empty():
    fake = FakeLLM(
        responses=[
            _tool_call("search_shop_policies_and_faqs", {"query": "ship to Mars"}),
            AIMessage(
                content="The store doesn't have a published policy on that — please contact the store."
            ),
        ]
    )
    node = make_support_node([_empty_policy_tool()], llm=fake)

    result = await node(_state("do you ship to Mars?"))

    text = result["messages"][-1].content.lower()
    assert "published policy" in text
    # The empty result was surfaced to the model (it had to decide from nothing).
    tool_message = next(m for m in fake.calls[1] if isinstance(m, ToolMessage))
    assert '"results":[]' in tool_message.content.replace(" ", "")


async def test_does_not_invent_policy():
    fake = FakeLLM(
        responses=[
            _tool_call("search_shop_policies_and_faqs", {"query": "warranty"}),
            AIMessage(
                content="The store hasn't published a policy on warranties; please contact the store."
            ),
        ]
    )
    node = make_support_node([_empty_policy_tool()], llm=fake)

    result = await node(_state("what's the warranty period?"))

    # The system prompt the model received carries the hard grounding rule.
    system = fake.calls[0][0]
    assert isinstance(system, SystemMessage)
    low = system.content.lower()
    assert "only" in low
    assert "search_shop_policies_and_faqs" in low
    assert "invent" in low  # "Inventing ... is strictly prohibited"
    # No fabricated duration leaked into the answer.
    assert "year" not in result["messages"][-1].content.lower()


async def test_refuses_tool_outside_policy_scope(fake_scoped_tools):
    # Support cannot reach the catalog/cart — its only grounding is the policy
    # tool, so an out-of-scope call is refused rather than sourced elsewhere.
    fake = FakeLLM(
        responses=[
            _tool_call("search_catalog", {"query": "black tee"}),
            AIMessage(content="Let me check the store policies instead."),
        ]
    )
    node = make_support_node(fake_scoped_tools["support"], llm=fake)

    result = await node(_state("is there a policy on this?"))

    tool_message = next(m for m in fake.calls[1] if isinstance(m, ToolMessage))
    assert "not available" in tool_message.content
    assert result["messages"][-1].content == "Let me check the store policies instead."
