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
# Shapes mirror what the live Storefront MCP returned during the Stage 1 verify
# spike: prices in MINOR units (paise — ₹399 -> 39900), product/variant ids in
# Shopify GID format, images on cdn.shopify.com. Returned to the model as JSON
# strings, exactly as the real tool results arrive.
# ---------------------------------------------------------------------------
_SEARCH_CATALOG_RESULT = {
    "products": [
        {
            "product_id": "gid://shopify/Product/8808632549464",
            "title": "Classic Black Tee",
            "description": "Soft combed-cotton crew neck in classic black.",
            "price_range": {"min": 39900, "max": 39900, "currency": "INR"},
            "image_url": "https://cdn.shopify.com/s/files/1/0/classic-black-tee.svg",
            "variants": [
                {"variant_id": "gid://shopify/ProductVariant/44221789601880", "title": "S", "price": 39900, "available": True},
                {"variant_id": "gid://shopify/ProductVariant/44221789634648", "title": "M", "price": 39900, "available": True},
                {"variant_id": "gid://shopify/ProductVariant/44221789667416", "title": "L", "price": 39900, "available": False},
            ],
        },
        {
            "product_id": "gid://shopify/Product/8808632582232",
            "title": "Oversized Charcoal Tee",
            "description": "Drop-shoulder oversized fit in heather charcoal.",
            "price_range": {"min": 59900, "max": 59900, "currency": "INR"},
            "image_url": "https://cdn.shopify.com/s/files/1/0/oversized-charcoal-tee.svg",
            "variants": [
                {"variant_id": "gid://shopify/ProductVariant/44221789700184", "title": "M", "price": 59900, "available": True},
                {"variant_id": "gid://shopify/ProductVariant/44221789732952", "title": "L", "price": 59900, "available": True},
            ],
        },
    ],
}

_PRODUCT_DETAILS_RESULT = {
    "product_id": "gid://shopify/Product/8808632549464",
    "title": "Classic Black Tee",
    "description": "Soft combed-cotton crew neck in classic black. 180 GSM, pre-shrunk.",
    "vendor": "Vastra",
    "product_type": "T-Shirts",
    "tags": ["tshirt", "black", "cotton", "everyday"],
    "image_urls": [
        "https://cdn.shopify.com/s/files/1/0/classic-black-tee.svg",
        "https://cdn.shopify.com/s/files/1/0/classic-black-tee-back.svg",
    ],
    "variants": [
        {"variant_id": "gid://shopify/ProductVariant/44221789601880", "title": "S", "price": 39900, "available": True},
        {"variant_id": "gid://shopify/ProductVariant/44221789634648", "title": "M", "price": 39900, "available": True},
        {"variant_id": "gid://shopify/ProductVariant/44221789667416", "title": "L", "price": 39900, "available": False},
        {"variant_id": "gid://shopify/ProductVariant/44221789700184", "title": "XL", "price": 39900, "available": True},
    ],
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
    def _get_cart(cart_id: str) -> str:
        return json.dumps(_GET_CART_RESULT)

    @staticmethod
    def _update_cart(cart_id: str, add_items: list | None = None) -> str:
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

    Returns a canned response without any network call, so agent and graph
    tests stay fully offline.
    """

    def __init__(self, response: str = "Here are a few options I found for you.", fallback_used: bool = False) -> None:
        self._response = response
        self._fallback_used = fallback_used

    @property
    def fallback_used(self) -> bool:
        return self._fallback_used

    async def ainvoke(self, messages, **kwargs):  # noqa: ANN001 - mirrors LangChain signature
        return AIMessage(content=self._response)

    async def astream(self, messages, **kwargs):  # noqa: ANN001
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
