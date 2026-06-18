"""Server-Sent Events serialisation for the streaming chat endpoints.

The API streams a turn as a sequence of typed SSE events (``token``, ``route``,
``product_cards``, ``confirm_request``, ``cart_update``, ``error``, ``done``).
Two surfaces are exposed:

* :func:`sse_event` — the canonical wire format as a plain string
  (``"event: <type>\\ndata: <json>\\n\\n"``). This is the contract the frontend
  parses and the shape tests assert against.
* :func:`sse` — the same payload as an ``sse-starlette`` :class:`ServerSentEvent`,
  which is what the endpoint async generators actually yield into an
  :class:`EventSourceResponse` (sse-starlette owns the byte framing, keep-alive
  pings, and client-disconnect handling for us).

Both serialise ``data`` with :func:`json.dumps` so there is a single source of
truth for the payload encoding.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from sse_starlette.sse import EventSourceResponse, ServerSentEvent

# Event types emitted by the chat / confirm streams. Kept here as the single
# vocabulary both endpoints and the frontend agree on.
EVENT_TOKEN = "token"
EVENT_ROUTE = "route"
EVENT_PRODUCT_CARDS = "product_cards"
EVENT_CONFIRM_REQUEST = "confirm_request"
EVENT_CART_UPDATE = "cart_update"
# Static nudge fired after an approved cart write succeeded; not an agent
# decision, so the API layer (not the graph) emits it.
EVENT_OUTFIT_PROMPT = "outfit_prompt"
EVENT_ERROR = "error"
EVENT_DONE = "done"


def sse_event(event_type: str, data: dict) -> str:
    """Serialise one SSE event to its canonical wire string.

    ``f"event: {event_type}\\ndata: {json.dumps(data)}\\n\\n"`` — the exact
    framing the frontend's ``EventSource`` parser consumes.
    """

    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse(event_type: str, data: dict) -> ServerSentEvent:
    """Build the ``ServerSentEvent`` an :class:`EventSourceResponse` yields.

    Carries the same ``event``/``data`` pair as :func:`sse_event`; sse-starlette
    renders the final bytes (and injects keep-alive comments) on the wire.
    """

    return ServerSentEvent(data=json.dumps(data, ensure_ascii=False), event=event_type)


def event_response(generator: AsyncIterator[Any]) -> EventSourceResponse:
    """Wrap a ``ServerSentEvent`` async generator as a streaming HTTP response.

    A large ``ping`` interval is used so keep-alive comment lines never interrupt
    a short turn's event sequence (turns complete in well under the interval).
    """

    return EventSourceResponse(generator, ping=3600)
