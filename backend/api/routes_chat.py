"""The core conversational endpoints — SSE streaming chat + cart confirmation.

``POST /api/chat`` runs one buyer turn through the LangGraph graph and streams
the result as Server-Sent Events. ``POST /api/confirm`` resolves a pending cart
mutation by resuming the graph from its ``interrupt()`` and streaming the
continuation. Both use the checkpointer-backed graph on ``app.state.graph`` keyed
by ``thread_id == session_id``, so conversation history and a paused cart write
survive across the two separate HTTP requests.

Event flow per ``/api/chat`` turn:

1. ``route``          — the supervisor's classification (stylist/cart/support).
2. ``token``          — the assistant reply text. The agent nodes invoke the LLM
   via ``ainvoke`` (not streaming) and the offline ``FakeLLM`` is not a LangChain
   Runnable, so ``astream_events`` emits no ``on_chat_model_stream`` chunks; we
   therefore replay the grounded *final* message as token events. This also
   prevents the supervisor's route JSON and intermediate ReAct turns from
   leaking to the buyer. A genuine ``on_chat_model_stream`` (if a future
   streaming model emits one) is passed through and suppresses the replay.
3. ``product_cards`` / ``cart_update`` — structured payloads, read ONLY from the
   final ``AIMessage.additional_kwargs`` (never parsed from text).
4. ``confirm_request`` — emitted instead of ``done`` when the graph pauses on a
   cart interrupt; the stream then ends and the client calls ``/api/confirm``.
5. ``done``           — ``{turn_id, fallback_used}`` once the turn completes.

The Preference Extractor runs as a fire-and-forget background task after the
reply is fully streamed; it never blocks the turn and any failure is swallowed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from backend.agents.extractor import extract_preferences, merge_profile
from backend.agents.suggestions import generate_suggestions
from backend.agents.supervisor import _message_text
from backend.db.queries import (
    get_buyer_profile,
    get_session,
    insert_message,
    update_session_activity,
    update_session_cart,
    upsert_buyer_profile,
)
from backend.streaming.sse import (
    EVENT_CART_UPDATE,
    EVENT_CONFIRM_REQUEST,
    EVENT_DONE,
    EVENT_OUTFIT_PROMPT,
    EVENT_PRODUCT_CARDS,
    EVENT_ROUTE,
    EVENT_TOKEN,
    event_response,
    sse,
)

# Static nudge payload — fired once after every approved cart write.
OUTFIT_PROMPT_PAYLOAD = {
    "message": "Want me to find pieces that go with it?",
    "action": "complete_look",
}

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

MAX_MESSAGE_CHARS = 1000
_SPECIALIST_NODES = {"stylist", "cart", "support", "complete_look"}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    session_id: str
    message: str


class ConfirmRequest(BaseModel):
    session_id: str
    action_id: str
    approved: bool = Field(default=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _profile_from_row(row: dict | None) -> dict:
    """Rebuild the in-memory buyer profile from a ``buyer_profiles`` row.

    ``sizes`` and ``style_tags`` are stored as JSON strings; decode them back to
    the dict/list shape the prompt injection and ``merge_profile`` expect.
    """

    if not row:
        return {}
    try:
        sizes = json.loads(row.get("sizes_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        sizes = {}
    try:
        tags = json.loads(row.get("style_tags") or "[]")
    except (json.JSONDecodeError, TypeError):
        tags = []
    return {
        "sizes": sizes if isinstance(sizes, dict) else {},
        "budget_min": row.get("budget_min"),
        "budget_max": row.get("budget_max"),
        "style_tags": tags if isinstance(tags, list) else [],
        "last_category": row.get("last_category"),
    }


def _token_chunks(text: str) -> list[str]:
    """Split reply text into word-sized token pieces for a streamed feel."""

    if not text:
        return []
    words = text.split(" ")
    return [w if i == len(words) - 1 else w + " " for i, w in enumerate(words)]


def _chunk_text(chunk: Any) -> str:
    """Flatten an ``on_chat_model_stream`` chunk to its text content."""

    content = getattr(chunk, "content", "")
    if isinstance(content, list):
        return "".join(
            str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in content
        )
    return str(content or "")


async def _run_extraction(app: Any, session_id: str, user_msg: str, assistant_msg: str) -> None:
    """Background task: extract a preference delta and upsert the buyer profile.

    Runs after the buyer-facing reply has already streamed, so it can never
    delay tokens. Any failure is logged and swallowed — memory is best-effort.
    """

    try:
        delta = await extract_preferences(user_msg, assistant_msg)
        if not delta:
            return
        existing = _profile_from_row(await get_buyer_profile(session_id))
        merged = merge_profile(existing, delta)
        await upsert_buyer_profile(
            session_id,
            json.dumps(merged.get("sizes", {})),
            merged.get("budget_min"),
            merged.get("budget_max"),
            json.dumps(merged.get("style_tags", [])),
            merged.get("last_category"),
        )
    except Exception as exc:  # noqa: BLE001 - extraction must never break a turn
        logger.warning("Preference extraction failed for %s: %s", session_id, exc)


def _schedule_extraction(app: Any, session_id: str, user_msg: str, assistant_msg: str) -> None:
    """Fire-and-forget the extractor, tracking the task so tests can await it."""

    bg: set = getattr(app.state, "bg_tasks", None)
    task = asyncio.create_task(_run_extraction(app, session_id, user_msg, assistant_msg))
    if isinstance(bg, set):
        bg.add(task)
        task.add_done_callback(bg.discard)


async def _pending_interrupt(graph: Any, config: dict) -> dict | None:
    """Return the pending interrupt payload for a thread, or None if resolved."""

    snapshot = await graph.aget_state(config)
    interrupts = getattr(snapshot, "interrupts", ()) or ()
    if interrupts:
        return interrupts[0].value
    return None


# Bound on the post-turn suggestion call so a slow 8B response can't extend a
# completed turn for more than half a second. If it trips, the ``done`` event
# still ships with ``suggestions: []`` and the frontend simply renders nothing.
SUGGESTION_TIMEOUT_SECS = 1.5


async def _safe_generate_suggestions(
    graph: Any, config: dict, final_text: str, default_route: str
) -> list[str]:
    """Read route + product_context off the latest snapshot, then await chips.

    Always returns a list — never raises. Returns ``[]`` when there's no reply
    text to base chips on, when the state read fails, when the timeout trips,
    or when the model itself errors.
    """

    if not final_text:
        return []
    try:
        snapshot = await graph.aget_state(config)
        values = getattr(snapshot, "values", {}) or {}
        route = values.get("route") or default_route or "respond"
        product_context = values.get("product_context") or []
    except Exception as exc:  # noqa: BLE001 - never block done on a state read
        logger.warning("State read for suggestions failed: %s", exc)
        return []
    try:
        return await asyncio.wait_for(
            generate_suggestions(final_text, route, product_context),
            timeout=SUGGESTION_TIMEOUT_SECS,
        )
    except asyncio.TimeoutError:
        logger.info("Suggestion generation exceeded %.1fs; emitting []", SUGGESTION_TIMEOUT_SECS)
        return []
    except Exception as exc:  # noqa: BLE001 - generate_suggestions already shields, defense in depth
        logger.warning("Suggestion generation raised: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Shared graph-event streaming
# ---------------------------------------------------------------------------
async def _stream_graph(
    graph: Any, graph_input: Any, config: dict
) -> AsyncIterator[Any]:
    """Run the graph and yield (sse_event, replay_event, final_text, fallback) tuples.

    A generator-of-generators would be awkward, so this yields a small dict per
    emission describing what to send and what to remember. The caller forwards
    ``sse`` to the wire and accumulates ``replay`` / ``final_text`` / ``fallback``
    / ``cart_id`` for persistence after the stream.
    """

    streamed_nodes: set[str] = set()

    async for ev in graph.astream_events(graph_input, config=config, version="v2"):
        kind = ev["event"]
        meta = ev.get("metadata") or {}
        node = meta.get("langgraph_node")
        data = ev.get("data") or {}

        if kind == "on_chat_model_stream" and node in _SPECIALIST_NODES:
            text = _chunk_text(data.get("chunk"))
            if text:
                streamed_nodes.add(node)
                yield {"sse": sse(EVENT_TOKEN, {"text": text})}
            continue

        if kind != "on_chain_end":
            continue

        name = ev.get("name")
        if name == "supervisor":
            route = (data.get("output") or {}).get("route")
            if route:
                yield {
                    "sse": sse(EVENT_ROUTE, {"agent": route}),
                    "replay": (EVENT_ROUTE, {"agent": route}),
                }
        elif name in _SPECIALIST_NODES:
            out = data.get("output") or {}
            if out.get("fallback_used"):
                yield {"fallback": True}
            messages = out.get("messages") or []
            if not messages:
                continue
            final = messages[-1]
            content = _message_text(final).strip()
            ak = getattr(final, "additional_kwargs", {}) or {}

            # Token replay — only when the model did not stream this node live.
            if content and name not in streamed_nodes:
                for piece in _token_chunks(content):
                    yield {"sse": sse(EVENT_TOKEN, {"text": piece})}
            if content:
                yield {"final_text": content}

            cards = ak.get("product_cards")
            if cards and cards.get("products"):
                yield {
                    "sse": sse(EVENT_PRODUCT_CARDS, cards),
                    "replay": (EVENT_PRODUCT_CARDS, cards),
                }
            cart_update = ak.get("cart_update")
            if cart_update:
                yield {
                    "sse": sse(EVENT_CART_UPDATE, cart_update),
                    "replay": (EVENT_CART_UPDATE, cart_update),
                    "cart_id": cart_update.get("cart_id") or "",
                }


# ---------------------------------------------------------------------------
# POST /api/chat
# ---------------------------------------------------------------------------
@router.post("/chat")
async def chat(request: Request, body: ChatRequest) -> Any:
    """Run one buyer turn and stream the result as Server-Sent Events."""

    session = await get_session(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if len(body.message) > MAX_MESSAGE_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Message exceeds {MAX_MESSAGE_CHARS} characters",
        )

    app = request.app
    graph = app.state.graph
    config = {"configurable": {"thread_id": body.session_id}}

    profile = _profile_from_row(await get_buyer_profile(body.session_id))
    # Persist the buyer's message up front so it survives a paused (interrupt)
    # turn or a mid-stream disconnect.
    await insert_message(body.session_id, "user", body.message)

    async def generator() -> AsyncIterator[Any]:
        graph_input = {
            "messages": [HumanMessage(content=body.message)],
            "buyer_profile": profile,
        }
        replay_events: list[tuple[str, dict]] = []
        final_text = ""
        fallback_used = False
        cart_id = ""
        last_route = ""

        async for emission in _stream_graph(graph, graph_input, config):
            if "sse" in emission:
                yield emission["sse"]
            if "replay" in emission:
                evt_name, evt_data = emission["replay"]
                replay_events.append(emission["replay"])
                if evt_name == EVENT_ROUTE:
                    last_route = evt_data.get("agent") or last_route
            if emission.get("final_text"):
                final_text = emission["final_text"]
            if emission.get("fallback"):
                fallback_used = True
            if emission.get("cart_id"):
                cart_id = emission["cart_id"]

        # Paused on a cart interrupt: surface the pending action and stop. The
        # turn is not done — the client resolves it via /api/confirm.
        pending = await _pending_interrupt(graph, config)
        if pending is not None:
            yield sse(EVENT_CONFIRM_REQUEST, pending)
            return

        # Turn complete — persist the assistant message + structured events.
        # A bare "respond" turn (greeting/thanks) produces no reply text and is
        # not persisted as an empty assistant bubble.
        turn_id: int | None = None
        if final_text:
            events_json = json.dumps(
                [{"event": e, "data": d} for e, d in replay_events]
            )
            turn_id = await insert_message(
                body.session_id, "assistant", final_text, events_json
            )
        if cart_id:
            await update_session_cart(body.session_id, cart_id)
        else:
            await update_session_activity(body.session_id)

        if final_text:
            _schedule_extraction(app, body.session_id, body.message, final_text)

        suggestions = await _safe_generate_suggestions(
            graph, config, final_text, last_route
        )

        yield sse(
            EVENT_DONE,
            {
                "turn_id": turn_id,
                "fallback_used": fallback_used,
                "suggestions": suggestions,
            },
        )

    return event_response(generator())


# ---------------------------------------------------------------------------
# POST /api/confirm
# ---------------------------------------------------------------------------
@router.post("/confirm")
async def confirm(request: Request, body: ConfirmRequest) -> Any:
    """Resolve a pending cart mutation by resuming the interrupted graph."""

    session = await get_session(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    app = request.app
    graph = app.state.graph
    config = {"configurable": {"thread_id": body.session_id}}

    pending = await _pending_interrupt(graph, config)
    if pending is None or pending.get("action_id") != body.action_id:
        # No pending action, or it was already resolved / superseded.
        raise HTTPException(status_code=409, detail="No matching pending action")

    async def generator() -> AsyncIterator[Any]:
        resume_input = Command(resume={"approved": body.approved})
        replay_events: list[tuple[str, dict]] = []
        final_text = ""
        fallback_used = False
        cart_id = ""
        last_route = ""
        cart_updated = False

        async for emission in _stream_graph(graph, resume_input, config):
            if "sse" in emission:
                yield emission["sse"]
            if "replay" in emission:
                evt_name, evt_data = emission["replay"]
                replay_events.append(emission["replay"])
                if evt_name == EVENT_ROUTE:
                    last_route = evt_data.get("agent") or last_route
                elif evt_name == EVENT_CART_UPDATE:
                    cart_updated = True
            if emission.get("final_text"):
                final_text = emission["final_text"]
            if emission.get("fallback"):
                fallback_used = True
            if emission.get("cart_id"):
                cart_id = emission["cart_id"]

        # Approved cart write succeeded → nudge the buyer to complete the look.
        # Captured into replay_events so the frontend rehydrates the prompt
        # alongside the assistant message when scrolling back through history.
        if body.approved and cart_updated:
            yield sse(EVENT_OUTFIT_PROMPT, OUTFIT_PROMPT_PAYLOAD)
            replay_events.append((EVENT_OUTFIT_PROMPT, OUTFIT_PROMPT_PAYLOAD))

        turn_id: int | None = None
        if final_text:
            events_json = json.dumps(
                [{"event": e, "data": d} for e, d in replay_events]
            )
            turn_id = await insert_message(
                body.session_id, "assistant", final_text, events_json
            )
        if cart_id:
            await update_session_cart(body.session_id, cart_id)
        else:
            await update_session_activity(body.session_id)

        suggestions = await _safe_generate_suggestions(
            graph, config, final_text, last_route
        )

        yield sse(
            EVENT_DONE,
            {
                "turn_id": turn_id,
                "fallback_used": fallback_used,
                "suggestions": suggestions,
            },
        )

    return event_response(generator())
