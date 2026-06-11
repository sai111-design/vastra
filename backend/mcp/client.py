"""Scoped MCP tool loading for the Shopify Storefront MCP endpoint.

Tools are discovered dynamically at startup from the live store's
``/api/mcp`` endpoint and then partitioned into per-agent scopes. Each
specialist agent only ever sees the tools it is allowed to call — the
supervisor never hands the Cart agent a catalog search, and so on.

The catalog tool is exposed by Shopify as ``search_catalog`` (the PRD's
``search_shop_catalog`` was an assumption corrected during the Stage 1 MCP
spike — see Agent/implementations.md).
"""

from __future__ import annotations

import logging

from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)

# Per-agent tool allow-lists. The union of these sets is the complete set of
# tools the application expects the Storefront MCP to expose.
SCOPES: dict[str, set[str]] = {
    "stylist": {"search_catalog", "get_product_details"},
    "cart": {"get_cart", "update_cart"},
    "support": {"search_shop_policies_and_faqs"},
}

# langchain-mcp-adapters has renamed / aliased the streaming HTTP transport
# across releases. Try the canonical name first, then documented fallbacks so
# the loader keeps working if the adapter version shifts under us.
_TRANSPORT_CANDIDATES: tuple[str, ...] = ("streamable_http", "http", "sse")


def _all_scoped_tool_names() -> set[str]:
    """Return the union of every agent's scoped tool names."""

    return set().union(*SCOPES.values())


def _partition(tools: list) -> dict[str, list]:
    """Split a flat tool list into the per-agent scope dict."""

    return {
        agent: [t for t in tools if t.name in names]
        for agent, names in SCOPES.items()
    }


async def _fetch_tools(url: str) -> list:
    """Connect to the MCP endpoint and return all discovered tools.

    Attempts each transport in :data:`_TRANSPORT_CANDIDATES` in order. A
    transport that the installed adapter does not recognise raises ``ValueError``
    at connection time; we move on to the next candidate. Any other error
    (network, protocol) propagates — we do not want to mask a dead endpoint by
    silently trying every transport.
    """

    last_error: Exception | None = None
    for transport in _TRANSPORT_CANDIDATES:
        client = MultiServerMCPClient(
            {
                "storefront": {
                    "transport": transport,
                    "url": url,
                }
            }
        )
        try:
            return await client.get_tools()
        except ValueError as exc:  # unsupported transport name on this adapter
            logger.debug("MCP transport %r rejected: %s", transport, exc)
            last_error = exc
            continue

    raise RuntimeError(
        f"Could not load MCP tools from {url}: no supported transport "
        f"(tried {', '.join(_TRANSPORT_CANDIDATES)})"
    ) from last_error


async def load_scoped_tools(store_domain: str) -> dict[str, list]:
    """Load tools from the Storefront MCP and partition them by agent scope.

    Args:
        store_domain: The ``*.myshopify.com`` host of the dev store.

    Returns:
        A dict keyed by agent name (``"stylist"``, ``"cart"``, ``"support"``)
        whose values are the subset of discovered tools that agent may call.
    """

    url = f"https://{store_domain}/api/mcp"
    tools = await _fetch_tools(url)

    discovered = {t.name for t in tools}
    logger.info("MCP tools discovered: %s", sorted(discovered))

    missing = _all_scoped_tool_names() - discovered
    if missing:
        logger.warning("MCP tools missing: %s", sorted(missing))

    return _partition(tools)
