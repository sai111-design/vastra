# Implementation Details — Vastra

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Orchestration | LangGraph ≥ 1.0 | Native checkpointers, interrupt/resume, MCP tool loading |
| LLM routing | Groq primary → Gemini Flash fallback | Zero cost; fastest free tier |
| Extraction model | Llama 3.1 8B Instant | Right-sized for background profile extraction; preserves 70B quota |
| Database access | psycopg 3, raw SQL | Portfolio convention — no ORM |
| MCP transport | `streamable_http` via langchain-mcp-adapters 0.3.0 | Storefront MCP uses JSON-RPC over HTTP; verified the adapter accepts this transport name (Stage 3) |
| MCP load API | `MultiServerMCPClient({server: {transport, url}}).get_tools()` | Single async call returns all tools; partitioned in-process by `SCOPES` |
| Groq error classes | `groq.RateLimitError` / `groq.APIConnectionError` (not `openai.*`) | langchain-groq ≥1.x ships the `groq` SDK; `openai` is not a dependency |
| Prompt injection boundary | Tool output wrapped in &lt;tool_data&gt; delimiters | MCP results are untrusted input |
| Cart safety | LangGraph interrupt() + Command(resume=) | Write-gating via platform primitive |
| Frontend | React 18 + Vite, plain JS, hand-written CSS | Portfolio convention — no UI libraries |
| Deployment | HF Spaces Docker SDK, SqliteSaver on /data | Free tier, persistent volume |
| MCP verification approach | Raw httpx JSON-RPC (no MCP library) | De-risk spike before committing to langchain-mcp-adapters |
| Catalog seeding | Shopify product CSV import format | Standard import path; 75 variants across 26 products covering 8 categories |
| Catalog tool name | `search_catalog` (not `search_shop_catalog`) | PRD assumed `search_shop_catalog` but actual Shopify MCP exposes `search_catalog` — all agent code must use the real name |
| DB connection driver | psycopg 3 `AsyncConnectionPool` (pkg `psycopg-pool`) + `aiosqlite` | Async, pooled Postgres; single shared SQLite connection for HF Spaces |
| Pool sizing / row factory | min 1 / max 10, autocommit=True, `dict_row` | Right-sized for a single-process demo; every query returns dicts and self-commits |
| Backend-agnostic SQL | One Postgres-dialect query set; thin `SqliteConn` translates at runtime | Keeps `queries.py` written once; SQLite path stays minimal (Stage 1 §"Keep the SQLite path simple") |
| SQLite timestamp default | `now()` → `CURRENT_TIMESTAMP` | A bare function call is invalid in a SQLite `DEFAULT` clause |
| Host Postgres port | `55432` (container stays 5432) | Dev box runs native PostgreSQL v13 (5432) and v18 (5433); high port avoids the clash |
| Windows async loop | Force `WindowsSelectorEventLoopPolicy` in tests | psycopg async cannot run on the Windows ProactorEventLoop (non-issue in Linux Docker) |
| Supervisor structured output | Prompt-engineered JSON + `parse_route()` (NOT `.with_structured_output()`) | Robust to Groq tool-calling quirks; clean "default to stylist" path on any parse failure |
| Stylist agent loop | Hand-rolled bounded ReAct (NOT `create_react_agent`) | Needs per-turn tool-call CAP, sanitiser on every result, and product_cards from raw tool JSON |
| product_cards transport | Final AIMessage `additional_kwargs` | Keeps `VastraState` exactly as specced; binds payload to the message for history replay |
| Prompt context injection | `str.replace("{buyer_profile}", …)` (NOT `str.format`) | Prompts are full of literal JSON braces; `.format` would require escaping them all |
| Tool budget accounting | Count EXECUTED tool calls; answer over-cap parallel calls with a "budget exhausted" ToolMessage | Enforces the 4-call cap while honouring the provider rule that every tool_call needs a response |
| MCP result flattening | `_content_to_text()` before sanitise/parse | Adapter tools (`content_and_artifact`) return content-block lists, not strings (Bug B009) |
| Unwired-route safety | `_route_or_end` maps cart/support/respond → END | A legal Stage-4 classification can't KeyError before Stage 5 wires those nodes |

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

## Database Layer (Implemented — Stage 2)

Source: `backend/db/schema.sql`, `backend/db/connection.py`, `backend/db/queries.py`.

4 application tables: sessions, messages, buyer_profiles, tool_call_log (+ `idx_messages_session`, `idx_toolcalls_session`). LangGraph checkpoint tables are created later by `checkpointer.setup()`.

### Connection management (`connection.py`)
- **Postgres:** lazily-opened `psycopg_pool.AsyncConnectionPool` (min 1, max 10), connections configured with `row_factory=dict_row` and `autocommit=True`.
- **SQLite:** one shared `aiosqlite` connection, `row_factory=aiosqlite.Row`, `PRAGMA foreign_keys=ON` (cascade deletes).
- `get_conn()` — async context manager yielding a backend-appropriate wrapper (`PostgresConn` / `SqliteConn`) exposing the same surface: `fetch_one`, `fetch_all`, `execute`, `insert_returning_id`.
- `init_db()` — reads `schema.sql`; Postgres runs each statement as-is, SQLite runs a translated script. Idempotent (`CREATE TABLE/INDEX IF NOT EXISTS`).
- `close_db()` — releases pool / shared connection (shutdown + tests).
- Connection failures are caught and re-raised as `RuntimeError` with context.

### SQLite translation approach
Queries are authored once in the Postgres dialect (`%s` placeholders, `now()`). The `SqliteConn` wrapper and schema loader apply purely textual translation — no second query set:

| Context | Postgres | SQLite |
|---------|----------|--------|
| Placeholder | `%s` | `?` |
| Current time (runtime + DEFAULT) | `now()` | `CURRENT_TIMESTAMP` |
| Timestamp type (DDL) | `TIMESTAMPTZ` | `TEXT` |
| Auto-id (DDL) | `BIGSERIAL PRIMARY KEY` | `INTEGER PRIMARY KEY AUTOINCREMENT` |
| `INSERT … RETURNING id` | native RETURNING | clause stripped; `cursor.lastrowid` |

This is deliberately narrow — it covers only the constructs the queries actually use, not arbitrary SQL.

### Query functions (`queries.py`) — all implemented, all parameterised
| Function | Returns |
|----------|---------|
| `create_session(session_id, store_domain)` | dict (id, store_domain, cart_id, created_at, last_active) |
| `get_session(session_id)` | dict \| None |
| `list_sessions()` | list[dict] — last_active DESC, each with truncated `preview` (first message, ≤120 chars) |
| `update_session_activity(session_id)` | None — touches last_active |
| `update_session_cart(session_id, cart_id)` | None |
| `insert_message(session_id, role, content, events_json=None)` | int (new id) |
| `get_messages(session_id)` | list[dict] — created_at ASC |
| `upsert_buyer_profile(session_id, sizes_json, budget_min, budget_max, style_tags, last_category)` | None — INSERT … ON CONFLICT DO UPDATE |
| `get_buyer_profile(session_id)` | dict \| None |
| `log_tool_call(session_id, agent, tool_name, args_json, status, confirmed, latency_ms)` | int (new id) |

### New dependencies (added to requirements.txt this stage)
- `psycopg-pool>=3.2` — async connection pool (separate from `psycopg[binary]`).
- `aiosqlite>=0.20` — async SQLite driver for the HF Spaces deployment path.

### Tests
`backend/tests/test_db_queries.py` — 8 tests (7 against live Postgres with per-test cascade cleanup, 1 full SQLite-translation round-trip). `backend/tests/conftest.py` forces the Windows selector event-loop policy. `pytest.ini` pins `asyncio_mode=auto` with session-scoped loops so the shared pool spans tests.

## MCP Tool Layer & LLM Fallback (Implemented — Stage 3)

Source: `backend/mcp/client.py`, `backend/mcp/sanitize.py`, `backend/llm/fallback.py`, `backend/tests/conftest.py`.

### Scoped tool loading (`mcp/client.py`)
- `SCOPES: dict[str, set[str]]` — the per-agent allow-lists; union == the 5 verified tools:
  - `stylist` → `{search_catalog, get_product_details}`
  - `cart` → `{get_cart, update_cart}`
  - `support` → `{search_shop_policies_and_faqs}`
  - Uses the **verified** catalog name `search_catalog` (the PRD/task snippet's `search_shop_catalog` is wrong — corrected in Stage 1).
- `load_scoped_tools(store_domain) -> dict[str, list]` — builds `https://{store_domain}/api/mcp`, loads via `MultiServerMCPClient(...).get_tools()`, logs discovered names (INFO), warns on any missing expected tool (WARNING), returns the `SCOPES` partition (keys always present; an unmet scope is an empty list).
- `_fetch_tools()` tries transports `("streamable_http", "http", "sse")` in order, advancing only when a transport name raises `ValueError`; real network/protocol errors propagate. Raises `RuntimeError` if every transport is rejected.

### Injection boundary (`mcp/sanitize.py`)
- `sanitize_tool_output(raw) -> "<tool_data>\n{raw}\n</tool_data>"` — fixed, well-known delimiter (the model is told via the system prompt that everything inside is data, never instructions). No attempt to detect/strip injection strings.
- `wrap_tool_call(fn)` — decorator applying the sanitiser to a tool's return value; handles sync and `async` callables and coerces non-str returns via `str()`.
- `TOOL_DATA_INSTRUCTION` — the exact sentence pasted into every system prompt (Stage 4 `prompts.py` will reference it).

### LLM fallback (`llm/fallback.py`)
- Model constants: `PRIMARY_MODEL="llama-3.3-70b-versatile"`, `SMALL_MODEL="llama-3.1-8b-instant"`, `FALLBACK_MODEL="gemini-2.0-flash"`.
- `FallbackChat(temperature=0.0, small=False)` — builds `ChatGroq` (primary) + `ChatGoogleGenerativeAI` (fallback).
  - `async ainvoke(messages, **kwargs)` — primary with one retry on `RateLimitError` (backoff `_backoff_seconds(attempt)=2**attempt`, patchable in tests); on `RateLimitError`/`APIConnectionError` after retry, sets `_fallback_used=True` and calls Gemini.
  - `fallback_used` property — read by the `done` SSE event.
- `FallbackChatStreaming(FallbackChat)` — adds `async astream(messages, **kwargs)` over `.astream()`; same retry/failover, but failover to Gemini happens **only before the first chunk is emitted** (a mid-stream failure re-raises, since restarting would duplicate output).
- **New dependency:** `groq>=0.11` added to requirements.txt — imported directly for its exception classes (already present transitively via `langchain-groq`, now explicit).

### Test fixtures (`tests/conftest.py`)
- `FakeMCPTools` — registers the 5 tool names as real `langchain_core.tools.StructuredTool`s (accurate name + arg schema) whose bodies return canned JSON. Accessors: `.all() -> list`, `.by_name() -> dict`.
- Canned response shapes (paise prices, GID ids — recorded from the Stage 1 verify spike):
  - `search_catalog(query)` → `{"products":[{product_id, title, description, price_range:{min,max,currency}, image_url, variants:[{variant_id,title,price,available}]}]}`
  - `get_product_details(product_id)` → `{product_id, title, description, vendor, product_type, tags, image_urls, variants:[…]}`
  - `get_cart(cart_id)` → `{cart_id, checkout_url, currency, subtotal, total_quantity, lines:[{line_id,variant_id,title,quantity,unit_price,line_price}]}`
  - `update_cart(cart_id, add_items?)` → same cart shape with updated quantities/subtotal
  - `search_shop_policies_and_faqs(query, context?)` → `{"results":[{title, content, source}]}`
- `fake_scoped_tools` fixture → partitions `FakeMCPTools.all()` through the production `SCOPES` (same `dict[str,list]` shape as `load_scoped_tools`).
- `fake_llm` fixture → `FakeLLM` with `ainvoke` (returns `AIMessage`) and `astream` (yields `AIMessageChunk`s) and a `fallback_used` property — no network.
- **All Stage 3+ tests use these doubles; none hit the live store or an LLM API.**

## Supervisor Graph & Stylist Agent (Implemented — Stage 4, MILESTONE A)

Source: `backend/agents/{state,prompts,supervisor,stylist,graph}.py`, `scripts/cli_chat.py`, `backend/llm/fallback.py` (`bind_tools`).

### State (`state.py`)
`VastraState(MessagesState)` — inherits the `messages` channel + `add_messages` reducer; adds `session_id`, `buyer_profile`, `product_context`, `cart_id`, `cart_snapshot`, `pending_action`, `route`, `fallback_used`, `turn_count`. Cart fields are reserved at Stage 4 so checkpoints created now stay forward-compatible with the Stage 5 cart flow. `product_context` is **replaced** (not appended) each time products are shown, holding only grounding refs `{id, title, url, variant_ids}`.

### Prompts (`prompts.py`)
Versioned constants, `PROMPT_VERSION = "2026-06-12.1"`. Runtime context injected by replacing the literal `{buyer_profile}` marker (`BUYER_PROFILE_MARKER`) via `.replace()`.
- **SUPERVISOR_PROMPT** — classifies the latest turn into `{stylist, cart, support, respond}`, emits `{"route": "..."}` only. Key rules encoded: cart requires an explicit transactional verb or cart reference (desire alone → stylist); ambiguity → stylist; greeting/thanks that also carries a request routes by the request; product-specific care Qs → stylist, store-wide policy → support.
- **STYLIST_PROMPT** — search → ≤4 picks → warm one-line-per-pick reply. Hard rules: never state a price/URL/name/availability not in this turn's tool output; empty results → drop weakest constraint (occasion→colour→budget, keep category) and retry once, then ask ONE clarifying question; apply profile silently; per-tool price-unit guidance (search=paise, details=rupees, always write ₹ in text); splices `TOOL_DATA_INSTRUCTION`; includes one worked tool-call example.
- **SUPPORT / CART / EXTRACTOR** — one-line placeholders (full text in Stage 5); exported now so imports are stable.

### Supervisor node (`supervisor.py`)
`supervisor_node(state) -> {"route", "turn_count"}`. Builds `[SystemMessage(SUPERVISOR_PROMPT+profile), *messages]`, trims to `CONTEXT_TOKEN_BUDGET`, calls a lazily-built shared `FallbackChat(temperature=0)` (`_get_llm()`, patched in tests), parses the route, increments `turn_count`.
- **`trim_messages(messages, budget)`** — keeps a leading `SystemMessage` + as many newest messages as fit, dropping oldest-middle first; always keeps the newest message even if it alone exceeds budget. Token estimate: `len(str(content))//4 + 8` per message (provider-independent, no tokenizer dep).
- **`parse_route(text)`** — bare-JSON parse → strip ``` fences → regex scan for `"route":"..."` → default `"stylist"`. Only values in `ROUTES` are accepted; everything else defaults. This is the "default to stylist on classification failure" acceptance criterion.
- `_message_text()` flattens str-or-parts-list content (Gemini fallback can return a parts list).

### Stylist node (`stylist.py`)
`make_stylist_node(tools, llm=None)` returns an async node running a **bounded ReAct loop**:
1. Build `[SystemMessage(STYLIST_PROMPT+profile), *trimmed messages]`; `chat = FallbackChat(temperature=0.3).bind_tools(tools)` (fresh per turn so `fallback_used` is per-turn accurate; `llm` is the test seam).
2. Loop while the model returns `tool_calls` and **executed calls < `MAX_TOOL_CALLS_PER_TURN`**: run each call via `tool.ainvoke(args)`, append a `ToolMessage`. Over-cap parallel calls in the same response get a "budget exhausted" `ToolMessage` (not executed) so every `tool_call` is answered.
3. If the cap is hit with calls still pending, answer the danglers and force one final text reply.
4. Emit a **fresh** `AIMessage(content=text, additional_kwargs={"product_cards": …})` — never the model's tool-call message — so no dangling `tool_calls` reach the checkpointer. Empty model text falls back to a factless line (makes no product claims).

Return: `{"messages": [final], "fallback_used": …}` plus `product_context` when products were shown. The intra-turn scratchpad (tool-call + tool-result messages) is deliberately **not** written to state.

- **Sanitiser boundary:** every raw tool result goes through `sanitize_tool_output()` (→ `<tool_data>` fences) before the model sees it; the raw (unfenced) JSON is also stashed for extraction.
- **`_content_to_text()`** flattens adapter content-block lists `[{"type":"text","text":…}]` → string before parse (Bug B009).

### product_cards extraction (`build_product_cards`)
Built **only** from `[(tool_name, raw_json), …]` collected during the loop — never model text. Per-tool extractors handle the two live shapes; results de-duplicate by product id, and a `get_product_details` result **merges into** an existing search card (`_merge_cards`: newer non-empty scalars win; variants are unioned by id so a details call — which returns only the selected variant — never strips the search result's other variant ids). Capped at 4. Price normalisation (`_to_rupees`): JSON *type* carries the unit convention — numbers are paise (`/100`), strings are already rupees → all emitted as major-unit strings (`"399.00"`). `_product_context_from_cards()` reduces cards to the `{id, title, url, variant_ids}` grounding refs stored in state.

### Graph (`graph.py`)
`build_graph(tools_by_agent, checkpointer=None, *, stylist_llm=None)`: nodes `supervisor` + `stylist`; `START→supervisor`; conditional edges via `_route_or_end` (wired route → its node, everything else → `END`) so cart/support/respond end cleanly until Stage 5; `stylist→END`. `stylist_llm` is a keyword-only test seam forwarded to the stylist node. **Deviation from the task snippet:** the raw `lambda s: s["route"]` selector would KeyError on a legal `cart`/`support` classification before those nodes exist — `_route_or_end` maps them to `END` instead.

### LLM wrapper change (`fallback.py`)
Added `FallbackChat.bind_tools(tools)` — binds tool defs to **both** primary and fallback models (a mid-turn failover must keep the same tool-calling contract) and returns `self`. Agents never import `ChatGroq`/`ChatGoogleGenerativeAI` directly (rules.md).

### CLI harness (`scripts/cli_chat.py`)
MILESTONE A verification tool (dev-only, never deployed): loads live scoped tools, builds the graph (no checkpointer), REPL that prints route/turn/fallback flag, assistant text, the full `product_cards` payload, and `product_context`. Turn-to-turn continuity comes from feeding the result state back as the next input. Sets the Windows selector loop policy + UTF-8 stdout (Bugs B004/B001).

### Tests (offline)
`test_agents_supervisor.py` (19) + `test_agents_stylist.py` (14) — both fully offline via `FakeLLM` (now scripts a `responses` sequence, records `calls`, no-op `bind_tools`) and the FakeMCP `StructuredTool`s. Full suite **68/68**.

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
