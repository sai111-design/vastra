"""Vastra CLI chat loop — the Stage 5 end-to-end verification tool.

Developer-only harness (never deployed): loads the live Storefront MCP tools,
builds the full supervisor graph (Stylist + Cart + Support) with an in-memory
checkpointer, and runs a REPL exercising every agent. Each turn prints the
route, the assistant's reply, and any structured payload (``product_cards`` /
``cart_update``) exactly as the frontend will receive it.

Cart writes pause the graph on a LangGraph ``interrupt()``: the loop prints the
pending action and asks the developer to approve (Y/N), then resumes with
``Command(resume={"approved": ...})`` — the same mechanism the Stage 6 SSE
layer will drive via ``confirm_request`` / ``/api/confirm``.

After each turn the Preference Extractor runs synchronously on the small model
and the accumulated ``buyer_profile`` is printed so you can watch it grow (in
the API this runs as a post-response background task).

Usage:
    python scripts/cli_chat.py
    (requires .env with SHOPIFY_STORE_DOMAIN + GROQ_API_KEY/GOOGLE_API_KEY)
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

# Fix Windows terminal encoding (Bug B001) before anything prints.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    # psycopg-compatible loop policy (Bug B004); harmless for this script and
    # keeps behaviour consistent with the rest of the backend on Windows.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from backend.agents.extractor import extract_preferences, merge_profile  # noqa: E402
from backend.agents.graph import build_graph  # noqa: E402
from backend.config import get_settings  # noqa: E402
from backend.mcp.client import load_scoped_tools  # noqa: E402

BOLD = "\033[1m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
MAGENTA = "\033[95m"
DIM = "\033[2m"
RESET = "\033[0m"


def _print_product_cards(cards: dict) -> None:
    """Render the structured payload the way the frontend will consume it."""

    products = cards.get("products", [])
    if not products:
        return

    print(f"\n{BOLD}{CYAN}── product_cards payload ({len(products)}) ──{RESET}")
    for product in products:
        price = product.get("price", {})
        print(f"  {BOLD}{product.get('title')}{RESET}  ₹{price.get('amount')} {price.get('currency')}")
        print(f"    id:    {product.get('id')}")
        print(f"    url:   {product.get('url')}")
        print(f"    image: {product.get('image_url')}")
        for variant in product.get("variants", []):
            mark = "✓" if variant.get("available") else "✗"
            print(f"      {mark} {variant.get('title')}  ({variant.get('id')})")
    print()


def _print_cart_update(cart: dict | None) -> None:
    """Render the cart_update payload the way the CartDrawer will consume it."""

    if not cart:
        return
    print(f"\n{BOLD}{CYAN}── cart_update payload ──{RESET}")
    print(f"  cart_id:  {cart.get('cart_id')}")
    print(f"  subtotal: ₹{cart.get('subtotal')} {cart.get('currency')}  ({cart.get('total_quantity')} items)")
    print(f"  checkout: {cart.get('checkout_url')}")
    for line in cart.get("lines", []):
        print(
            f"    • {line.get('title')} ×{line.get('quantity')}  "
            f"₹{line.get('line_price')}  ({line.get('variant_id')})"
        )
    print()


def _print_pending(pending: dict) -> None:
    """Show the proposed cart action awaiting confirmation."""

    line = pending.get("line", {})
    print(f"\n{BOLD}{YELLOW}⚠ confirm cart action [{pending.get('action_id')}]{RESET}")
    print(f"  {pending.get('summary')}")
    print(f"  {DIM}line: {json.dumps(line)}{RESET}")


async def _drive_turn(graph, turn_input, config) -> dict:
    """Invoke the graph and resolve any cart interrupts via Y/N prompts."""

    result = await graph.ainvoke(turn_input, config)
    while result.get("__interrupt__"):
        pending = result["__interrupt__"][0].value
        _print_pending(pending)
        try:
            answer = input(f"{BOLD}approve? [y/N]>{RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        approved = answer in {"y", "yes"}
        result = await graph.ainvoke(Command(resume={"approved": approved}), config)
    return result


async def main() -> int:
    settings = get_settings()
    print(f"{BOLD}Vastra CLI chat{RESET} — store: {settings.shopify_store_domain}")
    print(f"{DIM}Loading tools from the live Storefront MCP…{RESET}")

    tools_by_agent = await load_scoped_tools(settings.shopify_store_domain)
    for agent, tools in tools_by_agent.items():
        print(f"{DIM}  {agent}: {[t.name for t in tools]}{RESET}")

    # A checkpointer is required for the Cart interrupt/resume flow.
    graph = build_graph(tools_by_agent, checkpointer=MemorySaver())

    session_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}
    buyer_profile: dict = {}

    print(f"session: {session_id}")
    print("Type a message (or /quit to exit).\n")

    while True:
        try:
            user_input = input(f"{BOLD}you>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        if user_input.lower() in {"/quit", "/exit", "/q"}:
            break

        # Inject the accumulated profile each turn; the checkpointer carries the
        # message history and cart_id, so only the new message + profile go in.
        turn_input = {
            "messages": [{"role": "user", "content": user_input}],
            "buyer_profile": buyer_profile,
        }
        try:
            result = await _drive_turn(graph, turn_input, config)
        except Exception as exc:
            print(f"{YELLOW}error: {type(exc).__name__}: {exc}{RESET}\n")
            continue

        route = result.get("route", "?")
        flag = "  (fallback model)" if result.get("fallback_used") else ""
        print(f"{DIM}[route={route}  turn={result.get('turn_count')}]{flag}{RESET}")

        messages = result.get("messages", [])
        last = messages[-1] if messages else None
        assistant_text = ""
        if last is not None and getattr(last, "type", "") == "ai":
            assistant_text = last.content
            print(f"{GREEN}vastra>{RESET} {assistant_text}")
            _print_product_cards(last.additional_kwargs.get("product_cards", {}))
            _print_cart_update(last.additional_kwargs.get("cart_update"))
        else:
            # "respond" (greetings/thanks) ends at the supervisor with no
            # specialist message — expected.
            print(f"{DIM}(no specialist response — route '{route}' ends at the supervisor){RESET}")

        if result.get("product_context"):
            ctx = json.dumps(result["product_context"], indent=2)[:400]
            print(f"{DIM}product_context: {ctx}…{RESET}")

        # Preference extraction runs AFTER the buyer-facing reply (synchronous
        # here; a background task in Stage 6). Never let it break the turn.
        if assistant_text:
            try:
                delta = await extract_preferences(user_input, assistant_text)
            except Exception as exc:  # noqa: BLE001
                print(f"{DIM}(extractor skipped: {type(exc).__name__}){RESET}")
                delta = {}
            if delta:
                buyer_profile = merge_profile(buyer_profile, delta)
                print(f"{DIM}extracted delta: {json.dumps(delta)}{RESET}")
        print(f"{MAGENTA}buyer_profile:{RESET} {json.dumps(buyer_profile)}\n")

    print("bye!")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
