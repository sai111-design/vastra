"""Shared pytest fixtures and test-environment setup.

Two responsibilities:

1. Force the Windows ``SelectorEventLoop`` so psycopg's async path works (the
   ProactorEventLoop default is incompatible — see Bug B004).
2. Provide the offline test doubles every Stage 3+ test relies on: ``FakeMCPTools``
   (the 5 Storefront MCP tools with schema-accurate canned responses recorded
   from the Stage 1 verify spike), a ``fake_scoped_tools`` fixture matching the
   shape of ``load_scoped_tools()``, and a ``fake_llm`` fixture. Tests must never
   reach the live store or a real LLM API.
"""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import asynccontextmanager

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.tools import StructuredTool

from backend.mcp.client import SCOPES

# psycopg's async implementation cannot run on the Windows ProactorEventLoop
# (the platform default). Force the SelectorEventLoop policy for the whole test
# session before pytest-asyncio creates any loop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# ---------------------------------------------------------------------------
# Canned MCP responses
#
# search_catalog and get_product_details shapes were RE-RECORDED from the live
# Storefront MCP during Stage 4 (the Stage 1 spike only logged a truncated
# preview, and the real shapes differ from what Stage 3 inferred):
#   * search_catalog: products use "id", price_range.min/max are nested
#     {"amount": <paise int>, "currency"} objects, availability is nested under
#     "availability", images hang off each variant's "media" — and the payload
#     carries a server-supplied "instructions" field (untrusted!).
#   * get_product_details: {"product": {...}, "instructions": "..."} with
#     "product_id", price strings in MAJOR units ("399.0"), a flat "available"
#     bool, and only selectedOrFirstAvailableVariant (no full variants list).
# Cart and policy shapes are still the Stage 1/3 recordings (revisited Stage 5).
# ---------------------------------------------------------------------------
_SEARCH_CATALOG_RESULT = {
    "products": [
        {
            "id": "gid://shopify/Product/8808632549464",
            "title": "Classic Black Tee",
            "description": {"html": "Essential crew-neck t-shirt in soft cotton jersey."},
            "url": "https://vastra-demo.myshopify.com/products/classic-black-tee",
            "price_range": {
                "min": {"amount": 39900, "currency": "INR"},
                "max": {"amount": 39900, "currency": "INR"},
            },
            "variants": [
                {
                    "id": "gid://shopify/ProductVariant/44221789601880",
                    "title": "S / Black",
                    "price": {"amount": 39900, "currency": "INR"},
                    "availability": {"available": True},
                    "options": [{"name": "Size", "label": "S"}, {"name": "Color", "label": "Black"}],
                    "media": [{"type": "image", "url": "https://cdn.shopify.com/s/files/1/0/classic-black-tee.svg"}],
                },
                {
                    "id": "gid://shopify/ProductVariant/44221789634648",
                    "title": "M / Black",
                    "price": {"amount": 39900, "currency": "INR"},
                    "availability": {"available": True},
                    "options": [{"name": "Size", "label": "M"}, {"name": "Color", "label": "Black"}],
                    "media": [{"type": "image", "url": "https://cdn.shopify.com/s/files/1/0/classic-black-tee.svg"}],
                },
                {
                    "id": "gid://shopify/ProductVariant/44221789667416",
                    "title": "L / Black",
                    "price": {"amount": 39900, "currency": "INR"},
                    "availability": {"available": False},
                    "options": [{"name": "Size", "label": "L"}, {"name": "Color", "label": "Black"}],
                    "media": [{"type": "image", "url": "https://cdn.shopify.com/s/files/1/0/classic-black-tee.svg"}],
                },
            ],
        },
        {
            "id": "gid://shopify/Product/8808632582232",
            "title": "Oversized Charcoal Tee",
            "description": {"html": "Drop-shoulder oversized fit in heather charcoal."},
            "url": "https://vastra-demo.myshopify.com/products/oversized-charcoal-tee",
            "price_range": {
                "min": {"amount": 59900, "currency": "INR"},
                "max": {"amount": 59900, "currency": "INR"},
            },
            "variants": [
                {
                    "id": "gid://shopify/ProductVariant/44221789700184",
                    "title": "M / Charcoal",
                    "price": {"amount": 59900, "currency": "INR"},
                    "availability": {"available": True},
                    "options": [{"name": "Size", "label": "M"}, {"name": "Color", "label": "Charcoal"}],
                    "media": [{"type": "image", "url": "https://cdn.shopify.com/s/files/1/0/oversized-charcoal-tee.svg"}],
                },
                {
                    "id": "gid://shopify/ProductVariant/44221789732952",
                    "title": "L / Charcoal",
                    "price": {"amount": 59900, "currency": "INR"},
                    "availability": {"available": True},
                    "options": [{"name": "Size", "label": "L"}, {"name": "Color", "label": "Charcoal"}],
                    "media": [{"type": "image", "url": "https://cdn.shopify.com/s/files/1/0/oversized-charcoal-tee.svg"}],
                },
            ],
        },
    ],
    "pagination": {"limit": 10, "hasNextPage": False},
    "instructions": "Use markdown to render product titles as links.",
}

_PRODUCT_DETAILS_RESULT = {
    "product": {
        "product_id": "gid://shopify/Product/8808632549464",
        "title": "Classic Black Tee",
        "description": "Essential crew-neck t-shirt in soft cotton jersey.",
        "url": "https://vastra-demo.myshopify.com/products/classic-black-tee",
        "image_url": "https://cdn.shopify.com/s/files/1/0/classic-black-tee.svg",
        "images": [{"url": "https://cdn.shopify.com/s/files/1/0/classic-black-tee.svg", "alt_text": None}],
        "options": [
            {"name": "Size", "values": ["S", "M", "L", "XL"]},
            {"name": "Color", "values": ["Black"]},
        ],
        "total_variants": 4,
        "price_range": {"min": "399.0", "max": "399.0", "currency": "INR"},
        "selectedOrFirstAvailableVariant": {
            "variant_id": "gid://shopify/ProductVariant/44221789601880",
            "title": "S / Black",
            "price": "399.0",
            "currency": "INR",
            "image_url": "https://cdn.shopify.com/s/files/1/0/classic-black-tee.svg",
            "available": True,
            "selected_options": [{"name": "Size", "value": "S"}, {"name": "Color", "value": "Black"}],
        },
    },
    "instructions": "Pay attention to the selected variant specified in the response.",
}

_GET_CART_RESULT = {
    "cart_id": "gid://shopify/Cart/c1-abc123def456",
    "checkout_url": "https://vastra-demo.myshopify.com/cart/c/c1-abc123def456",
    "currency": "INR",
    "subtotal": 79800,
    "total_quantity": 2,
    "lines": [
        {
            "line_id": "gid://shopify/CartLine/1",
            "variant_id": "gid://shopify/ProductVariant/44221789634648",
            "title": "Classic Black Tee - M",
            "quantity": 2,
            "unit_price": 39900,
            "line_price": 79800,
        }
    ],
}

_UPDATE_CART_RESULT = {
    "cart_id": "gid://shopify/Cart/c1-abc123def456",
    "checkout_url": "https://vastra-demo.myshopify.com/cart/c/c1-abc123def456",
    "currency": "INR",
    "subtotal": 119700,
    "total_quantity": 3,
    "lines": [
        {
            "line_id": "gid://shopify/CartLine/1",
            "variant_id": "gid://shopify/ProductVariant/44221789634648",
            "title": "Classic Black Tee - M",
            "quantity": 3,
            "unit_price": 39900,
            "line_price": 119700,
        }
    ],
}

_POLICIES_RESULT = {
    "results": [
        {
            "title": "Returns & Exchanges",
            "content": (
                "Items can be returned or exchanged within 7 days of delivery, "
                "provided tags are intact and the item is unworn. Refunds are "
                "issued to the original payment method within 5-7 business days."
            ),
            "source": "returns.md",
        },
        {
            "title": "Shipping",
            "content": (
                "Free standard shipping on orders of Rs.999 or more. Express "
                "delivery available at checkout. Cash on delivery supported."
            ),
            "source": "shipping.md",
        },
    ],
}


# ---------------------------------------------------------------------------
# FakeMCPTools — offline stand-in for the live Storefront MCP
# ---------------------------------------------------------------------------
class FakeMCPTools:
    """Registers the 5 Storefront MCP tool names with canned JSON responses.

    Each tool is a real LangChain ``StructuredTool`` so it carries an accurate
    name and arg schema and can be invoked exactly like a tool loaded from the
    live MCP — only the body returns a fixed payload instead of making a network
    call.
    """

    def __init__(self) -> None:
        self._tools = [
            StructuredTool.from_function(
                func=self._search_catalog,
                name="search_catalog",
                description="Search the store catalog for products matching a query.",
            ),
            StructuredTool.from_function(
                func=self._get_product_details,
                name="get_product_details",
                description="Fetch full details and variants for one product by id.",
            ),
            StructuredTool.from_function(
                func=self._get_cart,
                name="get_cart",
                description="Retrieve the current contents of a cart by id.",
            ),
            StructuredTool.from_function(
                func=self._update_cart,
                name="update_cart",
                description="Add, update, or remove items in a cart.",
            ),
            StructuredTool.from_function(
                func=self._search_policies,
                name="search_shop_policies_and_faqs",
                description="Search store policies and FAQs for an answer.",
            ),
        ]

    # -- canned tool bodies -------------------------------------------------
    @staticmethod
    def _search_catalog(query: str) -> str:
        return json.dumps(_SEARCH_CATALOG_RESULT)

    @staticmethod
    def _get_product_details(product_id: str) -> str:
        return json.dumps(_PRODUCT_DETAILS_RESULT)

    @staticmethod
    def _get_cart(cart_id: str = "") -> str:
        return json.dumps(_GET_CART_RESULT)

    @staticmethod
    def _update_cart(cart_id: str = "", add_items: list | None = None) -> str:
        # cart_id is optional: the live update_cart creates a cart when absent.
        return json.dumps(_UPDATE_CART_RESULT)

    @staticmethod
    def _search_policies(query: str, context: str = "") -> str:
        return json.dumps(_POLICIES_RESULT)

    # -- accessors ----------------------------------------------------------
    def all(self) -> list:
        """Return all 5 fake tools as a flat list."""

        return list(self._tools)

    def by_name(self) -> dict[str, object]:
        """Return the fake tools keyed by tool name."""

        return {t.name: t for t in self._tools}


# ---------------------------------------------------------------------------
# FakeLLM — offline stand-in for FallbackChat
# ---------------------------------------------------------------------------
class FakeLLM:
    """Mock LLM exposing the FallbackChat surface (``ainvoke`` / ``astream``).

    Returns canned responses without any network call, so agent and graph
    tests stay fully offline.

    * ``response`` — single canned text reply (the Stage 3 behaviour).
    * ``responses`` — optional scripted sequence of ``AIMessage``s consumed in
      order by successive ``ainvoke`` calls (the last one repeats once the
      script is exhausted). Lets stylist tests script tool-call turns.
    * ``calls`` — records the message list passed to every ``ainvoke``/
      ``astream`` so tests can assert on prompt construction.
    * ``bind_tools`` — no-op that records the bound tools and returns self,
      mirroring ``FallbackChat.bind_tools``.
    """

    def __init__(
        self,
        response: str = "Here are a few options I found for you.",
        fallback_used: bool = False,
        responses: list | None = None,
    ) -> None:
        self._response = response
        self._responses = list(responses) if responses else None
        self._fallback_used = fallback_used
        self.calls: list = []
        self.bound_tools: list = []

    @property
    def fallback_used(self) -> bool:
        return self._fallback_used

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001 - mirrors FallbackChat
        self.bound_tools = list(tools)
        return self

    async def ainvoke(self, messages, **kwargs):  # noqa: ANN001 - mirrors LangChain signature
        self.calls.append(list(messages))
        if self._responses is not None:
            index = min(len(self.calls) - 1, len(self._responses) - 1)
            return self._responses[index]
        return AIMessage(content=self._response)

    async def astream(self, messages, **kwargs):  # noqa: ANN001
        self.calls.append(list(messages))
        for word in self._response.split(" "):
            yield AIMessageChunk(content=word + " ")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_mcp_tools() -> FakeMCPTools:
    """Provide a fresh :class:`FakeMCPTools` registry."""

    return FakeMCPTools()


@pytest.fixture
def fake_scoped_tools(fake_mcp_tools: FakeMCPTools) -> dict[str, list]:
    """Return tools partitioned by agent scope — the shape of ``load_scoped_tools``.

    Uses the production :data:`SCOPES` partition over the fake tools, so tests
    exercise the same scoping contract the live loader produces.
    """

    tools = fake_mcp_tools.all()
    return {
        agent: [t for t in tools if t.name in names]
        for agent, names in SCOPES.items()
    }


@pytest.fixture
def fake_llm() -> FakeLLM:
    """Provide a canned-response LLM that never calls a real provider."""

    return FakeLLM()


# ---------------------------------------------------------------------------
# API test harness (Stage 6) — offline FastAPI app over SQLite + FakeMCP
# ---------------------------------------------------------------------------
def parse_sse(text: str) -> list[dict]:
    """Parse a raw ``text/event-stream`` body into a list of {event, data} dicts.

    Tolerant of sse-starlette's ``\\r\\n`` framing and keep-alive comment lines
    (``: ping``). ``data`` is returned as the raw string; callers ``json.loads``
    it for the payload.
    """

    events: list[dict] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        block = block.strip("\n")
        if not block.strip():
            continue
        event = "message"
        data_lines: list[str] = []
        saw_field = False
        for line in block.split("\n"):
            if line.startswith(":"):  # comment / keep-alive ping
                continue
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
                saw_field = True
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].lstrip())
                saw_field = True
        if not saw_field:
            continue
        events.append({"event": event, "data": "\n".join(data_lines)})
    return events


@pytest.fixture
def sqlite_env(tmp_path, monkeypatch):
    """Point the whole config/DB layer at a throwaway SQLite file, offline.

    Switches ``DB_BACKEND=sqlite`` with a temp path, clears the cached settings
    singleton, and resets the connection-module globals so a fresh connection is
    opened against the test database. Restored on teardown.
    """

    import backend.db.connection as connection
    from backend.config import get_settings

    monkeypatch.setenv("DB_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "vastra_test.db"))
    monkeypatch.setenv("SHOPIFY_STORE_DOMAIN", "fake-store.myshopify.com")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("CORS_ORIGIN", "http://localhost:5173")

    get_settings.cache_clear()
    connection._pool = None
    connection._sqlite_conn = None
    yield
    get_settings.cache_clear()
    connection._pool = None
    connection._sqlite_conn = None


@pytest.fixture
def make_api_client(sqlite_env, fake_scoped_tools, monkeypatch):
    """Factory: build an offline FastAPI app + httpx client over the test graph.

    httpx's ASGITransport does NOT run lifespan events, so the production MCP
    load / checkpointer setup never fires — we wire ``app.state`` directly with
    the FakeMCP-scoped tools, a MemorySaver-backed graph, and offline LLM seams.
    The Preference Extractor is patched to a no-op by default (a test that asserts
    on memory overrides it). Background extraction tasks are drained on teardown.
    """

    import backend.agents.supervisor as supervisor_module
    import backend.api.routes_chat as routes_chat
    from httpx import ASGITransport, AsyncClient

    async def _noop_extract(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(routes_chat, "extract_preferences", _noop_extract)

    @asynccontextmanager
    async def _factory(
        *, supervisor_llm=None, stylist_llm=None, cart_llm=None, support_llm=None
    ):
        from langgraph.checkpoint.memory import MemorySaver

        from backend.agents.graph import build_graph
        from backend.config import get_settings
        from backend.db.connection import close_db, init_db
        from backend.main import create_app

        if supervisor_llm is not None:
            monkeypatch.setattr(supervisor_module, "_get_llm", lambda: supervisor_llm)

        await init_db()
        app = create_app()
        app.state.settings = get_settings()
        app.state.tools_by_agent = fake_scoped_tools
        app.state.graph = build_graph(
            fake_scoped_tools,
            MemorySaver(),
            stylist_llm=stylist_llm,
            cart_llm=cart_llm,
            support_llm=support_llm,
        )
        app.state.bg_tasks = set()

        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        try:
            yield client, app
        finally:
            pending = list(app.state.bg_tasks)
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            await client.aclose()
            await close_db()

    return _factory
