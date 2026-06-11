# Implementation Details — Vastra

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Orchestration | LangGraph ≥ 1.0 | Native checkpointers, interrupt/resume, MCP tool loading |
| LLM routing | Groq primary → Gemini Flash fallback | Zero cost; fastest free tier |
| Extraction model | Llama 3.1 8B Instant | Right-sized for background profile extraction; preserves 70B quota |
| Database access | psycopg 3, raw SQL | Portfolio convention — no ORM |
| MCP transport | Streamable HTTP via langchain-mcp-adapters | Storefront MCP uses JSON-RPC over HTTP |
| Prompt injection boundary | Tool output wrapped in &lt;tool_data&gt; delimiters | MCP results are untrusted input |
| Cart safety | LangGraph interrupt() + Command(resume=) | Write-gating via platform primitive |
| Frontend | React 18 + Vite, plain JS, hand-written CSS | Portfolio convention — no UI libraries |
| Deployment | HF Spaces Docker SDK, SqliteSaver on /data | Free tier, persistent volume |
| MCP verification approach | Raw httpx JSON-RPC (no MCP library) | De-risk spike before committing to langchain-mcp-adapters |
| Catalog seeding | Shopify product CSV import format | Standard import path; 75 variants across 26 products covering 8 categories |
| Catalog tool name | `search_catalog` (not `search_shop_catalog`) | PRD assumed `search_shop_catalog` but actual Shopify MCP exposes `search_catalog` — all agent code must use the real name |

## MCP Endpoint Details (Verified ✓)

**Endpoint:** `https://{SHOPIFY_STORE_DOMAIN}/api/mcp`
**Protocol:** JSON-RPC 2.0
**Protocol Version:** 2025-03-26
**Server:** storefront-renderer v0.1.0
**Authentication:** None (public endpoint — storefront password must be disabled on dev stores)

### Verified Tools

| # | Tool Name | PRD Name | Params | Status |
|---|-----------|----------|--------|--------|
| 1 | `search_catalog` | `search_shop_catalog` | `meta: object, catalog: object` (catalog.query for search text) | ✅ Verified — **name differs from PRD** |
| 2 | `get_cart` | `get_cart` | `cart_id: string` | ✅ Verified |
| 3 | `update_cart` | `update_cart` | `cart_id, add_items, update_items, remove_line_ids, buyer_identity, delivery_addresses_to_add, delivery_addresses_to_replace, selected_delivery_options, discount_codes, gift_card_codes, note` | ✅ Verified |
| 4 | `search_shop_policies_and_faqs` | `search_shop_policies_and_faqs` | `query: string, context: string` | ✅ Verified |
| 5 | `get_product_details` | `get_product_details` | `product_id: string, options: object, country: string, language: string` | ✅ Verified |

### Key Observations from MCP Spike

- **Price format:** Prices are returned in **minor units** (paise). ₹399 → `39900`. Frontend must divide by 100.
- **Product IDs:** GID format — `gid://shopify/Product/8808632549464`, `gid://shopify/ProductVariant/44221789601880`
- **UCP version in response:** `2026-04-08` — responses include a UCP wrapper with capabilities metadata
- **search_catalog params:** Uses nested object `{"catalog": {"query": "..."}}` not a flat `{"query": "..."}`
- **Images:** Served from `cdn.shopify.com` — the placeholder URLs from import were replaced with Shopify CDN SVGs
- **Capabilities:** Server supports `tools`, `prompts`, `resources`, `logging` with `listChanged: true`

### MCP Response Handling

The verify script handles two possible response formats:
1. Standard JSON-RPC response body
2. SSE-style or newline-delimited JSON (fallback parsing)

## API Endpoints (Planned)

| Method | Route | Purpose |
|--------|-------|---------|
| POST | /api/sessions | Create a session (= LangGraph thread) |
| GET | /api/sessions | List sessions for history view |
| GET | /api/sessions/{id} | Replay conversation + stored events |
| POST | /api/chat | Run one buyer turn (SSE stream) |
| POST | /api/confirm | Resolve pending cart action (SSE continuation) |
| GET | /api/health | Liveness: DB + MCP + model status |

## SSE Event Types (Planned)

| Event | Payload | Consumer |
|-------|---------|----------|
| token | { text } | MessageList (streamed text) |
| route | { agent } | Status line |
| product_cards | { products: [...] } | ProductCardRow |
| confirm_request | { action_id, summary, line } | ConfirmChip |
| cart_update | { cart_id, lines, subtotal, checkout_url } | CartDrawer |
| error | { message, recoverable } | Error bubble |
| done | { turn_id, fallback_used } | Stream close |

## Database Schema (Planned)
See backend/db/schema.sql — 4 application tables: sessions, messages, buyer_profiles, tool_call_log. LangGraph checkpoint tables created by checkpointer.setup().

## Component Map (Planned)

| Component | Responsibility |
|-----------|---------------|
| ChatView | Session composition root; owns turn state |
| MessageList / Composer | Bubbles + input |
| ProductCardRow / ProductCard | Renders ONLY from product_cards event payload |
| ConfirmChip | Confirm/Cancel → POST /api/confirm |
| CartDrawer | Slide-over from cart_update events |
| CheckoutBanner | Shopify checkout link handoff |
| SessionList | History via GET /api/sessions |

## Seed Catalog Summary

| Category | Products | Variant Rows | Price Range (₹) |
|----------|----------|-------------|----------------|
| T-Shirts | 5 | 16 | 399–549 |
| Oversized Tees | 3 | 9 | 599–699 |
| Jeans | 2 | 6 | 999–1099 |
| Joggers | 3 | 8 | 699–799 |
| Dresses | 3 | 9 | 799–1099 |
| Kurtas | 3 | 9 | 699–1299 |
| Sneakers | 3 | 11 | 799–1499 |
| Accessories | 4 | 7 | 299–599 |
| **Total** | **26** | **75** | **299–1499** |

## Environment Variables

| Variable | Purpose | Source |
|----------|---------|--------|
| GROQ_API_KEY | Primary LLM | Groq console |
| GOOGLE_API_KEY | Fallback LLM | Google AI Studio |
| SHOPIFY_STORE_DOMAIN | Storefront MCP host | Shopify Partners |
| DB_BACKEND | postgres or sqlite | Config |
| DATABASE_URL | Postgres DSN | Docker / manual |
| SQLITE_PATH | HF Spaces persistent path | /data/vastra.db |
| MAX_TOOL_CALLS_PER_TURN | ReAct loop hard cap | Default: 4 |
| CONTEXT_TOKEN_BUDGET | Message window trim target | Default: 6000 |
| LANGSMITH_TRACING | Enable/disable tracing | Default: false |
| APP_ENV | dev / prod | Config |

---
*This file is updated by the agent at the end of every stage.*
