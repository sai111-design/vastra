"""
Day-1 spike: raw JSON-RPC against Shopify Storefront MCP endpoint.

Verifies that the Shopify dev store's MCP endpoint is reachable and functional
before any application code is written. This is a de-risk script — if MCP doesn't
work on dev stores, the team pivots to direct Storefront GraphQL.

Usage:
    python scripts/verify_mcp.py

Requires:
    - httpx (listed in requirements.txt)
    - .env file with SHOPIFY_STORE_DOMAIN set

Steps performed:
    1. Send JSON-RPC 'initialize' → print server capabilities
    2. Send JSON-RPC 'tools/list' → print all tool names and schemas
    3. Send JSON-RPC 'tools/call' with search_catalog("black t-shirt") → print results
    4. Handle errors with clear diagnostics (connection refused, 404, rate-limited, etc.)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Fix Windows terminal encoding for Unicode symbols (✓, ✗, ⚠)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx
from dotenv import load_dotenv

# ── Colour helpers for terminal output ──────────────────────────────────────

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"{GREEN}✓ {msg}{RESET}")


def warn(msg: str) -> None:
    print(f"{YELLOW}⚠ {msg}{RESET}")


def err(msg: str) -> None:
    print(f"{RED}✗ {msg}{RESET}")


def header(msg: str) -> None:
    print(f"\n{BOLD}{CYAN}{'─' * 60}")
    print(f"  {msg}")
    print(f"{'─' * 60}{RESET}\n")


# ── JSON-RPC helpers ────────────────────────────────────────────────────────

def make_jsonrpc_request(
    method: str,
    params: dict | None = None,
    req_id: int = 1,
) -> dict:
    """Build a JSON-RPC 2.0 request payload."""
    payload: dict = {
        "jsonrpc": "2.0",
        "method": method,
        "id": req_id,
    }
    if params is not None:
        payload["params"] = params
    return payload


def send_rpc(
    client: httpx.Client,
    url: str,
    method: str,
    params: dict | None = None,
    req_id: int = 1,
) -> dict:
    """Send a JSON-RPC request and return the parsed response.

    Raises RuntimeError on HTTP or JSON-RPC level errors with
    human-readable diagnostics.
    """
    payload = make_jsonrpc_request(method, params, req_id)

    print(f"  → POST {url}")
    print(f"    method: {method}")

    try:
        resp = client.post(
            url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=30.0,
        )
    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"Connection refused — is the store domain correct?\n"
            f"  URL: {url}\n"
            f"  Detail: {exc}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise RuntimeError(
            f"Request timed out after 30 s.\n"
            f"  URL: {url}\n"
            f"  Detail: {exc}"
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"HTTP transport error: {exc}\n"
            f"  URL: {url}"
        ) from exc

    # ── HTTP-level diagnostics ──
    if resp.status_code == 404:
        raise RuntimeError(
            f"404 Not Found — the MCP endpoint does not exist at {url}.\n"
            f"  Is Storefront MCP enabled on this dev store?\n"
            f"  Response body: {resp.text[:500]}"
        )
    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "unknown")
        raise RuntimeError(
            f"429 Rate Limited — Shopify is throttling requests.\n"
            f"  Retry-After: {retry_after}\n"
            f"  Wait and try again."
        )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"HTTP {resp.status_code} error from {url}\n"
            f"  Response body: {resp.text[:500]}"
        )

    # ── Parse JSON-RPC response ──
    try:
        data = resp.json()
    except json.JSONDecodeError:
        # Shopify MCP may respond with SSE-style content or newline-delimited JSON
        # Try parsing the first line or the last JSON object
        lines = resp.text.strip().splitlines()
        data = None
        for line in reversed(lines):
            line = line.strip()
            if line.startswith("data:"):
                line = line[5:].strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
        if data is None:
            raise RuntimeError(
                f"Response is not valid JSON.\n"
                f"  Content-Type: {resp.headers.get('content-type', 'unknown')}\n"
                f"  Body (first 500 chars): {resp.text[:500]}"
            )

    if "error" in data:
        rpc_err = data["error"]
        raise RuntimeError(
            f"JSON-RPC error {rpc_err.get('code', '?')}: {rpc_err.get('message', '?')}\n"
            f"  Data: {json.dumps(rpc_err.get('data', {}), indent=2)}"
        )

    return data


# ── Main verification steps ─────────────────────────────────────────────────

def step_initialize(client: httpx.Client, url: str) -> dict:
    """Step 1: Send initialize and print server capabilities."""
    header("Step 1 — Initialize MCP session")

    data = send_rpc(
        client,
        url,
        method="initialize",
        params={
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "vastra", "version": "0.1.0"},
        },
        req_id=1,
    )

    result = data.get("result", {})
    server_info = result.get("serverInfo", {})
    capabilities = result.get("capabilities", {})
    protocol = result.get("protocolVersion", "unknown")

    ok(f"Server: {server_info.get('name', 'unknown')} v{server_info.get('version', '?')}")
    ok(f"Protocol version: {protocol}")
    print(f"\n  Capabilities:")
    print(f"  {json.dumps(capabilities, indent=4)}")

    return data


def step_tools_list(client: httpx.Client, url: str) -> list[dict]:
    """Step 2: List available tools and print their schemas."""
    header("Step 2 — List available tools")

    data = send_rpc(
        client,
        url,
        method="tools/list",
        params={},
        req_id=2,
    )

    tools = data.get("result", {}).get("tools", [])
    if not tools:
        warn("No tools returned — this may indicate the store has no storefront data.")
        return []

    ok(f"Found {len(tools)} tool(s):")
    print()

    expected_tools = {
        "search_catalog",
        "get_product_details",
        "update_cart",
        "get_cart",
        "search_shop_policies_and_faqs",
    }
    found_names = set()

    for i, tool in enumerate(tools, 1):
        name = tool.get("name", "unnamed")
        description = tool.get("description", "No description")
        schema = tool.get("inputSchema", {})
        found_names.add(name)

        marker = "✓" if name in expected_tools else "?"
        print(f"  {GREEN if name in expected_tools else YELLOW}{marker}{RESET} [{i}] {BOLD}{name}{RESET}")
        print(f"      {description[:120]}")
        if schema.get("properties"):
            props = schema["properties"]
            params_str = ", ".join(
                f"{k}: {v.get('type', '?')}" for k, v in props.items()
            )
            print(f"      Params: ({params_str})")
        print()

    # Check for expected tools
    missing = expected_tools - found_names
    extra = found_names - expected_tools
    if missing:
        warn(f"Missing expected tools: {', '.join(sorted(missing))}")
    if extra:
        warn(f"Extra tools not in PRD: {', '.join(sorted(extra))}")
    if not missing:
        ok("All expected PRD tools are present!")

    return tools


def step_test_search(client: httpx.Client, url: str) -> dict | None:
    """Step 3: Test a catalog search for 'black t-shirt'."""
    header("Step 3 — Test catalog search: 'black t-shirt'")

    data = send_rpc(
        client,
        url,
        method="tools/call",
        params={
            "name": "search_catalog",
            "arguments": {
                "catalog": {"query": "black t-shirt"},
            },
        },
        req_id=3,
    )

    result = data.get("result", {})
    content = result.get("content", [])

    if not content:
        warn("Search returned empty content — is the catalog imported?")
        return result

    ok(f"Search returned {len(content)} content block(s)")
    print()

    # Print the first content block (usually text with product info)
    for block in content[:3]:
        block_type = block.get("type", "unknown")
        if block_type == "text":
            text = block.get("text", "")
            # Truncate long output for readability
            display = text[:1500] + ("…" if len(text) > 1500 else "")
            print(f"  {display}")
        else:
            print(f"  [{block_type} block]: {json.dumps(block)[:300]}")
        print()

    return result


# ── Entry point ─────────────────────────────────────────────────────────────

def main() -> int:
    """Run the MCP verification spike."""
    # Load .env from project root
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        ok(f"Loaded .env from {env_path}")
    else:
        warn(f".env not found at {env_path} — falling back to environment variables")

    store_domain = os.getenv("SHOPIFY_STORE_DOMAIN", "").strip()
    if not store_domain or store_domain == "your-dev-store.myshopify.com":
        err(
            "SHOPIFY_STORE_DOMAIN is not set or still has the placeholder value.\n"
            "  Set it in your .env file:\n"
            "    SHOPIFY_STORE_DOMAIN=your-actual-store.myshopify.com"
        )
        return 1

    mcp_url = f"https://{store_domain}/api/mcp"

    header(f"Vastra MCP Verification Spike")
    print(f"  Store domain: {store_domain}")
    print(f"  MCP endpoint: {mcp_url}")

    with httpx.Client() as client:
        # Step 1: Initialize
        try:
            step_initialize(client, mcp_url)
        except RuntimeError as exc:
            err(f"Initialize failed:\n  {exc}")
            print(f"\n{YELLOW}Diagnostic: The MCP endpoint may not be available on this store.")
            print(f"Consider verifying that Storefront MCP is enabled, or pivot to")
            print(f"Storefront GraphQL API as a fallback.{RESET}")
            return 1

        # Step 2: List tools
        try:
            tools = step_tools_list(client, mcp_url)
        except RuntimeError as exc:
            err(f"tools/list failed:\n  {exc}")
            return 1

        # Step 3: Test search
        try:
            step_test_search(client, mcp_url)
        except RuntimeError as exc:
            err(f"Catalog search failed:\n  {exc}")
            warn("The catalog may not be imported yet. Import seed/catalog.csv into Shopify admin first.")
            return 1

    header("Verification Complete")
    ok("MCP endpoint is functional. Ready for Stage 2.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
