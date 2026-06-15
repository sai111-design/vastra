"""Supervisor-graph wiring.

Stage 4 ships the supervisor and the Stylist; the ``cart`` and ``support``
nodes (and their conditional edges) are added in Stage 5. Until then the
supervisor can still emit those routes — ``_route_or_end`` maps a route with
no node yet to ``END`` so the graph cannot crash on a valid classification.

``"respond"`` (greetings/thanks) intentionally ends the turn without invoking
a specialist; no assistant message is appended in Stage 4.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from backend.agents.state import VastraState
from backend.agents.stylist import make_stylist_node
from backend.agents.supervisor import supervisor_node

# Routes whose specialist nodes exist in this stage.
_WIRED_ROUTES = {"stylist"}


def _route_or_end(state: VastraState) -> str:
    """Conditional-edge selector: dispatch wired routes, end everything else."""

    route = state.get("route", "")
    return route if route in _WIRED_ROUTES else "__end__"


def build_graph(
    tools_by_agent: dict,
    checkpointer: Any = None,
    *,
    stylist_llm: Any = None,
):
    """Compile the Vastra supervisor graph.

    Args:
        tools_by_agent: Output of ``load_scoped_tools()`` (or the FakeMCP
            fixture) — per-agent tool lists keyed by agent name.
        checkpointer: Optional LangGraph checkpointer (None for the CLI;
            PostgresSaver/SqliteSaver from Stage 6).
        stylist_llm: Test seam forwarded to ``make_stylist_node`` so graph
            tests run offline; production leaves it None (FallbackChat).
    """

    g = StateGraph(VastraState)
    g.add_node("supervisor", supervisor_node)
    g.add_node("stylist", make_stylist_node(tools_by_agent["stylist"], llm=stylist_llm))
    # cart and support nodes added in Stage 5

    g.add_edge(START, "supervisor")
    g.add_conditional_edges(
        "supervisor",
        _route_or_end,
        {
            "stylist": "stylist",
            "__end__": END,
            # cart and support edges added in Stage 5
        },
    )
    g.add_edge("stylist", END)

    return g.compile(checkpointer=checkpointer)
