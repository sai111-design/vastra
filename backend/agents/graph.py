"""Supervisor-graph wiring.

The complete Stage 5 graph: the supervisor routes each turn to one of three
specialist nodes (Stylist, Cart, Support) or ends the turn for ``"respond"``
(greetings/thanks, no specialist). The Cart node may pause the graph with a
LangGraph ``interrupt()`` — running with a checkpointer is what makes that
interrupt/resume cycle work (the CLI and Stage 6 API both supply one).
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from backend.agents.cart import make_cart_node
from backend.agents.state import VastraState
from backend.agents.stylist import make_stylist_node
from backend.agents.supervisor import supervisor_node
from backend.agents.support import make_support_node

# Routes that dispatch to a specialist node. ``"respond"`` (and any unexpected
# value) ends the turn at the supervisor.
_SPECIALIST_ROUTES = {"stylist", "cart", "support"}


def _route_selector(state: VastraState) -> str:
    """Conditional-edge selector: dispatch a specialist, else end the turn."""

    route = state.get("route", "")
    return route if route in _SPECIALIST_ROUTES else "__end__"


def build_graph(
    tools_by_agent: dict,
    checkpointer: Any = None,
    *,
    stylist_llm: Any = None,
    cart_llm: Any = None,
    support_llm: Any = None,
):
    """Compile the Vastra supervisor graph.

    Args:
        tools_by_agent: Output of ``load_scoped_tools()`` (or the FakeMCP
            fixture) — per-agent tool lists keyed by agent name.
        checkpointer: Optional LangGraph checkpointer. REQUIRED for the Cart
            interrupt/resume flow (MemorySaver for the CLI/tests;
            PostgresSaver/SqliteSaver from Stage 6). None is fine for read-only
            or non-cart turns.
        stylist_llm / cart_llm / support_llm: Test seams forwarded to each
            specialist node so graph tests run offline; production leaves them
            None (each node builds its own FallbackChat).
    """

    g = StateGraph(VastraState)
    g.add_node("supervisor", supervisor_node)
    g.add_node("stylist", make_stylist_node(tools_by_agent["stylist"], llm=stylist_llm))
    g.add_node("cart", make_cart_node(tools_by_agent["cart"], llm=cart_llm))
    g.add_node("support", make_support_node(tools_by_agent["support"], llm=support_llm))

    g.add_edge(START, "supervisor")
    g.add_conditional_edges(
        "supervisor",
        _route_selector,
        {
            "stylist": "stylist",
            "cart": "cart",
            "support": "support",
            "__end__": END,
        },
    )
    for node in ("stylist", "cart", "support"):
        g.add_edge(node, END)

    return g.compile(checkpointer=checkpointer)
