"""Evaluation engine for Vastra golden and adversarial test cases.

Loads YAML test cases, replays conversations through the LangGraph graph
using FakeMCP + scripted FakeLLM fixtures, and asserts per-turn:

* Route assertion — supervisor routed to the expected agent
* Tool sequence assertion — expected tools called in order with key arguments
* Grounding assertion — no invented prices/URLs in the assistant reply
* Write-gating assertion — ``update_cart`` never called without approved interrupt
* Adversarial assertions — must_not_contain, must_not_call, max_tool_calls

All evals run fully offline (FakeMCP + scripted FakeLLM) — no network, no API.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

import backend.agents.supervisor as supervisor_module
from backend.agents.graph import build_graph
from backend.mcp.client import SCOPES


# ---------------------------------------------------------------------------
# Data classes for results
# ---------------------------------------------------------------------------
@dataclass
class TurnResult:
    """Result of one turn assertion."""

    turn_index: int
    user_message: str
    passed: bool = True
    failures: list[str] = field(default_factory=list)
    route_actual: str = ""
    route_expected: str = ""
    tools_called: list[str] = field(default_factory=list)
    reply_text: str = ""


@dataclass
class CaseResult:
    """Aggregated result for one YAML test case."""

    case_id: str
    description: str
    suite_type: str = "golden"
    turns: list[TurnResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(t.passed for t in self.turns)

    @property
    def pass_count(self) -> int:
        return sum(1 for t in self.turns if t.passed)

    @property
    def total_turns(self) -> int:
        return len(self.turns)


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------
def load_cases(directory: Path) -> list[dict]:
    """Discover and load all ``.yaml`` files from *directory*, sorted by name."""

    cases: list[dict] = []
    for path in sorted(directory.glob("*.yaml")):
        with open(path, encoding="utf-8") as fh:
            case = yaml.safe_load(fh)
            if case:
                cases.append(case)
    return cases


# ---------------------------------------------------------------------------
# Recording MCP tools — spy wrappers that capture every invocation
# ---------------------------------------------------------------------------
class RecordingMCPTools:
    """Wraps an existing ``FakeMCPTools`` instance with call recording.

    Every tool invocation is logged as ``{name, args, result}`` in
    :pyattr:`call_log`.  The wrapped tools keep the original signatures
    so ``StructuredTool`` schema inference works correctly.
    """

    def __init__(self, base_tools: Any) -> None:
        self.call_log: list[dict] = []
        self._base = base_tools
        self._tools = [self._make_spy(t) for t in base_tools.all()]

    def _make_spy(self, tool: StructuredTool) -> StructuredTool:
        base_func = tool.func
        log = self.call_log
        name = tool.name

        if name == "search_catalog":

            def fn(query: str) -> str:
                result = base_func(query=query)
                log.append({"name": name, "args": {"query": query}, "result": result})
                return result

        elif name == "get_product_details":

            def fn(product_id: str) -> str:
                result = base_func(product_id=product_id)
                log.append({"name": name, "args": {"product_id": product_id}, "result": result})
                return result

        elif name == "get_cart":

            def fn(cart_id: str = "") -> str:
                result = base_func(cart_id=cart_id)
                log.append({"name": name, "args": {"cart_id": cart_id}, "result": result})
                return result

        elif name == "update_cart":

            def fn(cart_id: str = "", add_items: list | None = None) -> str:
                result = base_func(cart_id=cart_id, add_items=add_items)
                log.append(
                    {"name": name, "args": {"cart_id": cart_id, "add_items": add_items}, "result": result}
                )
                return result

        elif name == "search_shop_policies_and_faqs":

            def fn(query: str, context: str = "") -> str:
                result = base_func(query=query, context=context)
                log.append({"name": name, "args": {"query": query, "context": context}, "result": result})
                return result

        else:

            def fn(**kwargs: Any) -> str:
                result = base_func(**kwargs)
                log.append({"name": name, "args": kwargs, "result": result})
                return result

        return StructuredTool.from_function(func=fn, name=name, description=tool.description)

    def all(self) -> list:
        return list(self._tools)

    def by_name(self) -> dict[str, Any]:
        return {t.name: t for t in self._tools}

    def scoped(self) -> dict[str, list]:
        """Partition into per-agent lists, same shape as ``load_scoped_tools``."""

        return {
            agent: [t for t in self._tools if t.name in names]
            for agent, names in SCOPES.items()
        }

    def calls_since(self, start: int) -> list[dict]:
        return self.call_log[start:]


# ---------------------------------------------------------------------------
# Scripted Eval FakeLLM — deterministic, offline
# ---------------------------------------------------------------------------
class EvalFakeLLM:
    """Returns pre-scripted AIMessage responses in sequence.

    When the scripted list is exhausted the last response repeats.
    """

    def __init__(
        self,
        responses: list[AIMessage] | None = None,
        default_response: str = "",
    ) -> None:
        self._responses = responses or []
        self._default = default_response
        self._call_index = 0
        self.calls: list = []
        self.bound_tools: list = []
        self._fallback_used = False

    @property
    def fallback_used(self) -> bool:
        return self._fallback_used

    def bind_tools(self, tools: Any, **kwargs: Any) -> "EvalFakeLLM":
        self.bound_tools = list(tools)
        return self

    async def ainvoke(self, messages: Any, **kwargs: Any) -> AIMessage:
        self.calls.append(list(messages))
        if self._call_index < len(self._responses):
            resp = self._responses[self._call_index]
            self._call_index += 1
            return resp
        if self._responses:
            return self._responses[-1]  # repeat last
        return AIMessage(content=self._default)


# ---------------------------------------------------------------------------
# Content-based Cart LLM (deterministic across node re-execution)
# ---------------------------------------------------------------------------
_DEFAULT_VARIANT = "gid://shopify/ProductVariant/44221789634648"


class EvalCartLLM:
    """Content-based fake LLM for cart turns — survives LangGraph re-execution.

    Decision logic mirrors the ``CartFakeLLM`` from ``test_agents_cart.py``:
    * ToolMessage present → return summary text
    * "show"/"what's in" → ``get_cart``
    * Anything else → propose ``update_cart`` for the default variant
    """

    def __init__(self, variant_id: str = _DEFAULT_VARIANT) -> None:
        self._variant_id = variant_id
        self.calls: list = []
        self.bound_tools: list = []
        self._fallback_used = False

    @property
    def fallback_used(self) -> bool:
        return self._fallback_used

    def bind_tools(self, tools: Any, **kwargs: Any) -> "EvalCartLLM":
        self.bound_tools = list(tools)
        return self

    async def ainvoke(self, messages: Any, **kwargs: Any) -> AIMessage:
        self.calls.append(list(messages))

        # After a tool result, summarise
        if any(isinstance(m, ToolMessage) for m in messages):
            return AIMessage(content="Done — your cart has been updated.")

        # Find the latest human text
        text = ""
        for m in messages:
            if isinstance(m, HumanMessage):
                text = str(m.content)
        low = text.lower()

        # Detect transactional verbs first — these are WRITES, not reads
        write_verbs = ("add ", "remove", "delete", "update", "change")
        is_write = any(verb in low for verb in write_verbs)

        # Read-only cart request (only if NOT a write)
        read_keywords = ("show", "what's in", "see my cart", "view cart", "checkout", "check out")
        if not is_write and any(kw in low for kw in read_keywords):
            return AIMessage(
                content="",
                tool_calls=[{"name": "get_cart", "args": {}, "id": "g1"}],
            )

        # Default: propose add (or any write operation)
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "update_cart",
                    "args": {"add_items": [{"variant_id": self._variant_id, "quantity": 1}]},
                    "id": "u1",
                }
            ],
        )


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------
_PRICE_RE = re.compile(r"₹[\d,]+(?:\.\d+)?|Rs\.?\s*[\d,]+(?:\.\d+)?")
_URL_RE = re.compile(r"https?://[^\s)\"'>\]]+")


def _assert_route(actual: str, expected: str) -> str | None:
    if actual != expected:
        return f"Route: expected '{expected}', got '{actual}'"
    return None


def _assert_tools(calls: list[dict], expected: list[dict]) -> list[str]:
    """Check expected tools appeared in order; optionally verify args_contains."""

    failures: list[str] = []
    if not expected:
        return failures

    call_idx = 0
    for exp in expected:
        exp_name = exp["name"]
        found = False
        while call_idx < len(calls):
            if calls[call_idx]["name"] == exp_name:
                # args_contains check
                if "args_contains" in exp:
                    actual_args = calls[call_idx].get("args", {})
                    actual_flat = json.dumps(actual_args, default=str).lower()
                    for key, value in exp["args_contains"].items():
                        if str(value).lower() not in actual_flat:
                            failures.append(
                                f"Tool '{exp_name}' args: expected key '{key}' to contain "
                                f"'{value}', args were {actual_args}"
                            )
                found = True
                call_idx += 1
                break
            call_idx += 1

        if not found:
            actual_names = [c["name"] for c in calls]
            failures.append(f"Expected tool '{exp_name}' not in call sequence {actual_names}")

    return failures


def _assert_grounding(reply_text: str, tool_results: list[str]) -> list[str]:
    """Every price and URL in the reply must exist in a tool result."""

    failures: list[str] = []
    if not reply_text:
        return failures

    combined = " ".join(tool_results)

    # Check prices
    for price_match in _PRICE_RE.findall(reply_text):
        numeric = re.sub(r"[₹Rs.\s,]", "", price_match)
        if not numeric:
            continue
        try:
            rupees = float(numeric)
            paise = int(rupees * 100)
            found = any(
                s in combined
                for s in (
                    numeric,
                    str(paise),
                    f"{rupees:.1f}",
                    f"{rupees:.2f}",
                    str(int(rupees)),
                )
            )
            if not found:
                failures.append(f"Grounding: price '{price_match}' not found in tool results")
        except ValueError:
            pass

    # Check URLs
    for url_match in _URL_RE.findall(reply_text):
        url_clean = url_match.rstrip(".,;:!?)")
        if url_clean not in combined:
            failures.append(f"Grounding: URL '{url_clean}' not found in tool results")

    return failures


def _assert_write_gating(calls: list[dict], had_approved_interrupt: bool) -> list[str]:
    """``update_cart`` must not be called without an approved interrupt."""

    failures: list[str] = []
    for call in calls:
        if call["name"] == "update_cart" and not had_approved_interrupt:
            failures.append("Write-gating: update_cart called without approved interrupt")
    return failures


def _assert_must_not_contain(reply_text: str, forbidden: list[str]) -> list[str]:
    failures: list[str] = []
    for term in forbidden:
        if term.lower() in reply_text.lower():
            failures.append(f"Adversarial: reply contains forbidden string '{term}'")
    return failures


def _assert_must_not_call(calls: list[dict], forbidden: list[str]) -> list[str]:
    failures: list[str] = []
    for call in calls:
        if call["name"] in forbidden:
            failures.append(f"Adversarial: forbidden tool '{call['name']}' was called")
    return failures


def _assert_max_tool_calls(calls: list[dict], max_calls: int) -> list[str]:
    if len(calls) > max_calls:
        return [f"Tool cap: {len(calls)} calls exceed max {max_calls}"]
    return []


def _assert_min_products_returned(product_count: int, minimum: int) -> list[str]:
    """The Stylist must surface at least ``minimum`` cards when several products match."""

    if product_count < minimum:
        return [
            f"Multi-result: expected ≥{minimum} product_cards, got {product_count} "
            "(Stylist narrowed too aggressively for a broad filtered query)"
        ]
    return []


def _assert_max_products_returned(product_count: int, maximum: int) -> list[str]:
    """A narrowing turn must collapse to at most ``maximum`` cards (typically 1)."""

    if product_count > maximum:
        return [
            f"Narrowing: expected ≤{maximum} product_cards, got {product_count} "
            "(Stylist did not collapse to a single item on the follow-up)"
        ]
    return []


# ---------------------------------------------------------------------------
# Build FakeLLMs from a YAML case
# ---------------------------------------------------------------------------
def _parse_ai_message(spec: Any) -> AIMessage:
    """Convert a YAML agent response spec into an AIMessage."""

    if isinstance(spec, str):
        return AIMessage(content=spec)
    content = spec.get("content", "")
    tool_calls = []
    for tc in spec.get("tool_calls", []):
        tool_calls.append(
            {
                "name": tc["name"],
                "args": tc.get("args", {}),
                "id": tc.get("id", f"tc_{uuid.uuid4().hex[:6]}"),
            }
        )
    return AIMessage(content=content, tool_calls=tool_calls if tool_calls else [])


def build_llms_from_case(case: dict) -> dict[str, Any]:
    """Pre-build all FakeLLMs for a case from the YAML turn specs."""

    supervisor_responses: list[AIMessage] = []
    stylist_responses: list[AIMessage] = []
    support_responses: list[AIMessage] = []
    has_cart_turns = False

    for turn in case.get("turns", []):
        llm_spec = turn.get("llm", {})
        expect = turn.get("expect", {})
        route = expect.get("route", "stylist")

        # Supervisor response
        sup_text = llm_spec.get("supervisor", f'{{"route": "{route}"}}')
        supervisor_responses.append(AIMessage(content=sup_text))

        # Check for cart turns
        if route == "cart" or turn.get("interrupt") is not None:
            has_cart_turns = True

        # Agent responses — dispatch to the right specialist list
        agent_specs = llm_spec.get("agent", [])
        target = {"stylist": stylist_responses, "support": support_responses}.get(route)
        if target is not None:
            for spec in agent_specs:
                target.append(_parse_ai_message(spec))

    return {
        "supervisor": EvalFakeLLM(
            responses=supervisor_responses,
            default_response='{"route": "stylist"}',
        ),
        "stylist": EvalFakeLLM(
            responses=stylist_responses if stylist_responses else None,
            default_response="I found some options for you.",
        ),
        "cart": EvalCartLLM() if has_cart_turns else EvalFakeLLM(default_response="Here is your cart."),
        "support": EvalFakeLLM(
            responses=support_responses if support_responses else None,
            default_response="Per our store policy, items can be returned within 7 days.",
        ),
    }


# ---------------------------------------------------------------------------
# Default product context (matches the FakeMCP canned search result)
# ---------------------------------------------------------------------------
_DEFAULT_PRODUCT_CTX: list[dict] = [
    {
        "id": "gid://shopify/Product/8808632549464",
        "title": "Classic Black Tee",
        "url": "https://vastra-demo.myshopify.com/products/classic-black-tee",
        "price": {"amount": "399.00", "currency": "INR"},
        "variant_ids": [
            "gid://shopify/ProductVariant/44221789601880",
            "gid://shopify/ProductVariant/44221789634648",
            "gid://shopify/ProductVariant/44221789667416",
        ],
        "variants": [
            {"id": "gid://shopify/ProductVariant/44221789601880", "title": "S / Black"},
            {"id": "gid://shopify/ProductVariant/44221789634648", "title": "M / Black"},
            {"id": "gid://shopify/ProductVariant/44221789667416", "title": "L / Black"},
        ],
    },
    {
        "id": "gid://shopify/Product/8808632582232",
        "title": "Oversized Charcoal Tee",
        "url": "https://vastra-demo.myshopify.com/products/oversized-charcoal-tee",
        "price": {"amount": "599.00", "currency": "INR"},
        "variant_ids": [
            "gid://shopify/ProductVariant/44221789700184",
            "gid://shopify/ProductVariant/44221789732952",
        ],
        "variants": [
            {"id": "gid://shopify/ProductVariant/44221789700184", "title": "M / Charcoal"},
            {"id": "gid://shopify/ProductVariant/44221789732952", "title": "L / Charcoal"},
        ],
    },
]


# ---------------------------------------------------------------------------
# Run a single YAML case
# ---------------------------------------------------------------------------
async def run_case(case: dict, mcp_tools: Any) -> CaseResult:
    """Execute one eval case (golden or adversarial) end-to-end.

    Args:
        case: Parsed YAML dict with ``id``, ``turns``, etc.
        mcp_tools: A ``FakeMCPTools`` (or ``AdversarialFakeMCPTools``) instance.

    Returns:
        A :class:`CaseResult` with per-turn pass/fail and failure details.
    """

    case_id = case.get("id", "unknown")
    description = case.get("description", "")
    suite_type = case.get("suite_type", "golden")

    result = CaseResult(case_id=case_id, description=description, suite_type=suite_type)

    # Spy-wrapped tools
    recording = RecordingMCPTools(mcp_tools)
    tools_by_agent = recording.scoped()

    # Build per-case FakeLLMs
    llms = build_llms_from_case(case)

    # Patch the supervisor's global LLM
    original_get_llm = supervisor_module._get_llm
    supervisor_module._get_llm = lambda: llms["supervisor"]  # type: ignore[assignment]

    try:
        graph = build_graph(
            tools_by_agent,
            checkpointer=MemorySaver(),
            stylist_llm=llms["stylist"],
            cart_llm=llms["cart"],
            support_llm=llms["support"],
        )

        thread_id = f"eval-{case_id}-{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}

        product_context = case.get("initial_product_context", _DEFAULT_PRODUCT_CTX)

        for i, turn_spec in enumerate(case.get("turns", [])):
            turn_result = TurnResult(
                turn_index=i,
                user_message=turn_spec.get("user", ""),
            )
            expect = turn_spec.get("expect", {})

            call_start = len(recording.call_log)

            try:
                inp: dict[str, Any] = {
                    "messages": [HumanMessage(content=turn_spec["user"])],
                    "buyer_profile": case.get("buyer_profile", {}),
                    "product_context": product_context,
                }

                out = await graph.ainvoke(inp, config)

                # Handle cart interrupts
                had_interrupt = "__interrupt__" in out
                had_approved_interrupt = False

                if had_interrupt and turn_spec.get("interrupt"):
                    approved = turn_spec.get("approved", False)
                    out = await graph.ainvoke(
                        Command(resume={"approved": approved}), config
                    )
                    had_approved_interrupt = approved

                # --- Extract results for assertion ---
                route = out.get("route", "")
                turn_result.route_actual = route
                turn_result.route_expected = expect.get("route", "")

                # Reply text + product_cards — both ride the last AIMessage.
                reply_text = ""
                product_count = 0
                msgs = out.get("messages", [])
                for msg in reversed(msgs):
                    if not isinstance(msg, AIMessage):
                        continue
                    if not msg.content and not getattr(msg, "additional_kwargs", None):
                        continue
                    if msg.content:
                        reply_text = str(msg.content)
                    ak = getattr(msg, "additional_kwargs", {}) or {}
                    cards = ak.get("product_cards") or {}
                    products = cards.get("products") or []
                    product_count = len(products)
                    break
                turn_result.reply_text = reply_text

                # Update product_context for next turn
                if out.get("product_context"):
                    product_context = out["product_context"]

                # Collect tool calls for this turn
                turn_calls = recording.calls_since(call_start)
                turn_result.tools_called = [c["name"] for c in turn_calls]

                # Tool results for grounding assertion
                turn_tool_results = [c["result"] for c in turn_calls if "result" in c]

                # --- Run assertions ---
                failures: list[str] = []

                if "route" in expect:
                    err = _assert_route(route, expect["route"])
                    if err:
                        failures.append(err)

                if "tools" in expect:
                    failures.extend(_assert_tools(turn_calls, expect["tools"]))

                if expect.get("reply_must_not_invent") and reply_text:
                    failures.extend(_assert_grounding(reply_text, turn_tool_results))

                failures.extend(_assert_write_gating(turn_calls, had_approved_interrupt))

                if "must_not_contain" in expect:
                    failures.extend(
                        _assert_must_not_contain(reply_text, expect["must_not_contain"])
                    )

                if "must_not_call" in expect:
                    failures.extend(_assert_must_not_call(turn_calls, expect["must_not_call"]))

                if "max_tool_calls" in expect:
                    failures.extend(
                        _assert_max_tool_calls(turn_calls, expect["max_tool_calls"])
                    )

                if "min_products_returned" in expect:
                    failures.extend(
                        _assert_min_products_returned(
                            product_count, expect["min_products_returned"]
                        )
                    )

                if "max_products_returned" in expect:
                    failures.extend(
                        _assert_max_products_returned(
                            product_count, expect["max_products_returned"]
                        )
                    )

                turn_result.passed = len(failures) == 0
                turn_result.failures = failures

            except Exception as exc:
                if expect.get("must_not_crash", True):
                    turn_result.passed = False
                    turn_result.failures = [f"Exception: {type(exc).__name__}: {exc}"]
                else:
                    # The case expected a crash is acceptable
                    turn_result.passed = True

            result.turns.append(turn_result)

    finally:
        supervisor_module._get_llm = original_get_llm  # type: ignore[assignment]

    return result


# ---------------------------------------------------------------------------
# Summary formatting
# ---------------------------------------------------------------------------
def format_summary(results: list[CaseResult], suite_type: str) -> str:
    """Render a markdown summary table of eval results."""

    lines: list[str] = []
    lines.append(f"\n## Evaluation Summary — {suite_type.title()} Suite\n")
    lines.append("| Case | Description | Turns | Passed | Failed | Status |")
    lines.append("|------|-------------|-------|--------|--------|--------|")

    total_cases = len(results)
    passed_cases = sum(1 for r in results if r.passed)

    for r in results:
        status = "PASS" if r.passed else "FAIL"
        failed = r.total_turns - r.pass_count
        desc = r.description[:50]
        lines.append(
            f"| {r.case_id} | {desc} | {r.total_turns} | "
            f"{r.pass_count} | {failed} | {status} |"
        )

    pass_rate = (passed_cases / total_cases * 100) if total_cases else 0
    lines.append(f"\n**Pass rate: {passed_cases}/{total_cases} ({pass_rate:.1f}%)**\n")

    # Failure details
    has_failures = False
    for r in results:
        if not r.passed:
            for t in r.turns:
                if not t.passed:
                    if not has_failures:
                        lines.append("### Failure Details\n")
                        has_failures = True
                    lines.append(f"**{r.case_id}** — Turn {t.turn_index}")
                    lines.append(f"  User: \"{t.user_message}\"")
                    for f in t.failures:
                        lines.append(f"  - {f}")
                    lines.append("")

    return "\n".join(lines)
