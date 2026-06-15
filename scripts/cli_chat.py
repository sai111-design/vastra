"""Vastra CLI chat loop — the MILESTONE A verification tool.

Developer-only harness (never deployed): loads the live Storefront MCP tools,
builds the Stage 4 supervisor graph, and runs a REPL. Each turn prints the
supervisor's route, the assistant's reply, and — when the Stylist ran — the
``product_cards`` payload exactly as the frontend will receive it.

Usage:
    python scripts/cli_chat.py
    (requires .env with SHOPIFY_STORE_DOMAIN + GROQ_API_KEY/GOOGLE_API_KEY)

No checkpointer is used; continuity across turns comes from feeding the full
result state back in as the next invocation's input.
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

from backend.agents.graph import build_graph  # noqa: E402
from backend.config import get_settings  # noqa: E402
from backend.mcp.client import load_scoped_tools  # noqa: E402

BOLD = "\033[1m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
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


async def main() -> int:
    settings = get_settings()
    print(f"{BOLD}Vastra CLI chat{RESET} — store: {settings.shopify_store_domain}")
    print(f"{DIM}Loading tools from the live Storefront MCP…{RESET}")

    tools_by_agent = await load_scoped_tools(settings.shopify_store_domain)
    for agent, tools in tools_by_agent.items():
        print(f"{DIM}  {agent}: {[t.name for t in tools]}{RESET}")

    graph = build_graph(tools_by_agent)  # no checkpointer for the CLI

    state: dict = {
        "messages": [],
        "session_id": str(uuid.uuid4()),
        "buyer_profile": {},
        "product_context": [],
        "cart_id": None,
        "cart_snapshot": None,
        "pending_action": None,
        "route": "",
        "fallback_used": False,
        "turn_count": 0,
    }
    print(f"session: {state['session_id']}")
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

        state["messages"] = list(state["messages"]) + [
            {"role": "user", "content": user_input}
        ]
        try:
            state = await graph.ainvoke(state)
        except Exception as exc:
            print(f"{YELLOW}error: {type(exc).__name__}: {exc}{RESET}\n")
            continue

        route = state.get("route", "?")
        flag = "  (fallback model)" if state.get("fallback_used") else ""
        print(f"{DIM}[route={route}  turn={state.get('turn_count')}]{flag}{RESET}")

        messages = state.get("messages", [])
        last = messages[-1] if messages else None
        if last is not None and getattr(last, "type", "") == "ai":
            print(f"{GREEN}vastra>{RESET} {last.content}")
            _print_product_cards(last.additional_kwargs.get("product_cards", {}))
        else:
            # "respond" (and unwired cart/support) end the turn without a
            # specialist — expected in Stage 4.
            print(f"{DIM}(no specialist response this turn — route '{route}' ends at the supervisor in Stage 4){RESET}\n")

        if state.get("product_context"):
            ctx = json.dumps(state["product_context"], indent=2)[:400]
            print(f"{DIM}product_context: {ctx}…{RESET}\n")

    print("bye!")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
