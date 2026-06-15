"""Shared LangGraph state for the Vastra supervisor graph.

``VastraState`` extends LangGraph's ``MessagesState`` (which contributes the
``messages`` channel with the ``add_messages`` append/upsert reducer). Every
node reads from and returns partial updates to this one state shape.

Conventions:

* ``product_context`` holds only grounding references (ids, titles, URLs,
  variant ids) for the products most recently *shown* to the buyer — enough
  for a later turn to resolve "the second one" or "the black tee" to a
  variant id without re-searching. It is replaced, not appended, whenever a
  new set of products is shown.
* ``route`` is written by the supervisor each turn and consumed by the
  conditional edge that dispatches to a specialist.
* ``pending_action`` / ``cart_snapshot`` are reserved for the Cart agent's
  interrupt flow (Stage 5); they are part of the schema now so checkpoints
  created at Stage 4 remain compatible.
"""

from __future__ import annotations

from typing import Optional

from langgraph.graph import MessagesState


class VastraState(MessagesState):
    """One buyer session's graph state (also the checkpointed thread state)."""

    session_id: str
    buyer_profile: dict          # injected from DB at turn start
    product_context: list[dict]  # handles + variant IDs of last shown products
    cart_id: Optional[str]
    cart_snapshot: Optional[dict]
    pending_action: Optional[dict]
    route: str                   # supervisor decision
    fallback_used: bool
    turn_count: int
