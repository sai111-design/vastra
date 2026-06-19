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
| SSE parsing | fetch + ReadableStream + TextDecoder async generator (NOT EventSource) | EventSource is GET-only; need POST for /api/chat and /api/confirm |
| State management | Single `useChatStream` hook with local accumulator pattern | No external state library; accumulator survives cart interrupt (stream ends without `done`) |
| View switching | `data-view` attribute + CSS media queries (NOT react-router) | Portfolio constraint; two views (sessions/chat) don't warrant a router |
| Cart interrupt UX | Stream `finally` block finalises accumulated message if no `done` received | The backend sends `confirm_request` then ENDS the stream; UI must show the chip from the partial message |
| Mobile layout | CSS media query at 768px; cart = bottom sheet; sidebar → full-screen session list | Single breakpoint covers phone/tablet/desktop; bottom sheet is native-feeling on mobile |
| Deployment | HF Spaces Docker SDK, SqliteSaver on /data | Free tier, persistent volume |
| Eval harness engine | YAML-driven, graph-level, fully offline (FakeMCP + scripted FakeLLM) | Deterministic CI, zero API cost, tests the pipeline not the LLM |
| Eval assertion types | Route, tool sequence, grounding (prices/URLs), write-gating, adversarial (must_not_contain/call/max_tool_calls), result-set size (min_products_returned/max_products_returned, F2) | Covers routing correctness, tool orchestration, hallucination boundary, safety, and the two-phase retrieval contract (broad recall on Phase 1, precision narrowing on Phase 2) |
| Eval FakeLLM strategy | `EvalFakeLLM` (scripted sequence) for supervisor/stylist/support; `EvalCartLLM` (content-based) for cart turns | Cart re-execution needs deterministic replay; content-based LLM survives node re-runs |
| Adversarial fixtures | `AdversarialFakeMCPTools` injects payloads into search/policy tool results | Same injection strings as `seed_injections.py` — CI and live-store test identical boundary |
| Eval tool recording | `RecordingMCPTools` spy wrappers capture name+args+result per call | Enables tool sequence, grounding, and write-gating assertions without modifying agent code |
| Grounding assertion scope | Checks prices (₹NNN) and URLs against tool results; does NOT check product names | Name matching is fuzzy (abbreviations, partials) — strict matching would cause brittle false positives |
| Eval pass thresholds | Golden ≥90%, Adversarial 100% | Safety failures have zero tolerance; golden allows for known agent quirks logged in progress.md |
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
| Stylist search shape (F2) | Two-phase pattern: broad result for category+filter, narrow on explicit follow-up | A buyer who says "jeans under ₹500, size 32" should see the whole matching shelf, not a single pick; narrowing happens only when the next message names a specific item ("the cheapest one", "the second one") |
| product_cards cap (F2) | `MAX_PRODUCT_CARDS = 8` (was 4) | Phase-1 broad results need to surface the matching shelf; 8 is a UX ceiling — overflow gets a "…and a few more" in prose, never a silent slice to 1 |
| search_catalog filter encoding | All filters (price ceiling, size, colour, occasion) ride in the natural-language `query` string | The live MCP tool schema is `{catalog:{query:string}}` only — there is no structured filter parameter to pass; the prompt instructs the model to encode every named filter into the query text |
| product_cards transport | Final AIMessage `additional_kwargs` | Keeps `VastraState` exactly as specced; binds payload to the message for history replay |
| Prompt context injection | `str.replace("{buyer_profile}", …)` (NOT `str.format`) | Prompts are full of literal JSON braces; `.format` would require escaping them all |
| Tool budget accounting | Count EXECUTED tool calls; answer over-cap parallel calls with a "budget exhausted" ToolMessage | Enforces the 4-call cap while honouring the provider rule that every tool_call needs a response |
| MCP result flattening | `_content_to_text()` before sanitise/parse | Adapter tools (`content_and_artifact`) return content-block lists, not strings (Bug B009) |
| Unwired-route safety | `_route_or_end` maps cart/support/respond → END | A legal Stage-4 classification can't KeyError before Stage 5 wires those nodes (superseded Stage 5: all routes wired, `_route_selector` sends respond/unknown → END) |
| Cart write-gating | `interrupt(pending)` inside the cart node; resume via `Command(resume={"approved": bool})` | Platform primitive; the pending payload becomes the `confirm_request` SSE event |
| pending_action surfacing | Lives in the interrupt PAYLOAD, not checkpointed state | A node that interrupts never returns, so it cannot also write state; the caller reads `result["__interrupt__"][0].value` |
| Cart node determinism | Content-based decisions, temperature 0, single side effect after approval | LangGraph re-executes the whole node on resume (LLM-before-interrupt runs twice) — only the post-approval `update_cart` may mutate |
| cart_id ownership | Node binds `cart_id` from state (or omits it); model-supplied ids dropped | The model never sees the cart_id; an absent id lets `update_cart` create a cart (live behaviour) |
| cart_update payload | Built from cart tool JSON only, carried in the final AIMessage `additional_kwargs` | Same grounding contract as Stylist `product_cards` — never render money from model text |
| product_context enrichment | Added `price` + per-variant `{id,title}` (kept `variant_ids`) | Cart restates the exact line (title/variant/price) from grounded refs, not model text |
| Extraction output | Prompt-engineered JSON + robust parse (NOT `.with_structured_output()`) | Same rationale as the supervisor; clean empty-delta fallback on any parse failure |
| Extraction model | `FallbackChat(temperature=0, small=True)` (Llama 3.1 8B) | Right-sized background task; preserves 70B quota; runs AFTER the buyer reply |
| Support grounding | Hard prompt rule (answer ONLY from tool, never invent); eval-verified | Free-text answers have no structured payload to enforce — the guarantee is the prompt + Stage 8 evals |
| Token streaming source | Replay the grounded final `AIMessage` (word-chunked), not raw `on_chat_model_stream` | Nodes use `ainvoke` (no model-stream events fire); raw streaming would also leak supervisor route JSON + intermediate ReAct text. Real chunks pass through when present (B012) |
| Structured event source | `additional_kwargs` of the specialist's final message (via `astream_events` `on_chain_end` output), never text | Same grounding contract as the agents; the API is a pass-through, not a re-parser |
| Interrupt → `confirm_request` | Read `aget_state().interrupts[0].value` AFTER the event loop; emit and hold (no `done`) | An `interrupt()` does not appear as a stream event (B013); `/api/confirm` validates `action_id` against the same snapshot before `Command(resume=...)` |
| Checkpointer (Stage 6) | `AsyncPostgresSaver`/`AsyncSqliteSaver.from_conn_string`, async CM nested around the lifespan `yield`; `await setup()` once | Async savers match the async stack; the CM keeps the connection alive for the app's life |
| Background extraction | `asyncio.create_task` tracked in `app.state.bg_tasks`, run after the streamed reply; `done` does not wait | Honest "background task" that never delays tokens; the tracking set lets tests `await` the upsert deterministically |
| Offline API tests | Wire `app.state` directly + `MemorySaver` (ASGITransport skips lifespan) | No network; the production AsyncPg/Sqlite savers are exercised via the real lifespan / curl (Milestone B) |

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

## API Endpoints (Implemented — Stage 6)

| Method | Route | Purpose |
|--------|-------|---------|
| POST | /api/sessions | Create a session (= LangGraph thread) |
| GET | /api/sessions | List sessions for history view |
| GET | /api/sessions/{id} | Replay conversation + stored events |
| POST | /api/chat | Run one buyer turn (SSE stream) |
| POST | /api/confirm | Resolve pending cart action (SSE continuation) |
| GET | /api/health | Liveness: DB + MCP + model status |

## SSE Event Types (Implemented — Stage 6, consumed by Stage 7 frontend)

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
`test_agents_supervisor.py` (19) + `test_agents_stylist.py` (14) — both fully offline via `FakeLLM` (now scripts a `responses` sequence, records `calls`, no-op `bind_tools`) and the FakeMCP `StructuredTool`s. Full suite **68/68** (Stage 4).

## Cart, Support & Preference Extractor (Implemented — Stage 5)

Source: `backend/agents/{cart,support,extractor}.py`, updated `graph.py`, `prompts.py`, `stylist.py`, `scripts/cli_chat.py`. `PROMPT_VERSION = "2026-06-15.1"`.

### Cart node (`cart.py`) — the interrupt/confirm safety gate
`make_cart_node(tools, llm=None)` returns an async bounded ReAct loop over `get_cart`/`update_cart`. The write invariant (rules.md): `update_cart` never runs without an explicit, approved confirmation.

The interrupt flow (verified live against LangGraph 1.0.3):
1. The model emits an `update_cart` tool call. The node does **not** run it — it builds a `pending` action and calls `interrupt(pending)`. The graph pauses; `graph.ainvoke(...)` returns with `result["__interrupt__"][0].value == pending`.
2. The caller resumes via `graph.ainvoke(Command(resume={"approved": bool}), config)`. **LangGraph re-executes the whole node from the top** — the LLM-before-interrupt runs a second time — and `interrupt()` now *returns* the resume value instead of pausing. Only on `{"approved": True}` is `update_cart` invoked. On denial (or a malformed resume) the node returns `"No problem — your cart is unchanged."` and `pending_action: None`, with **no** tool call.
3. Because of the re-execution, everything before the interrupt must be deterministic: the model runs at temperature 0 and the sole durable side effect (the tool call) happens strictly after approval.

`pending` payload (future `confirm_request` event): `{action_id: uuid4().hex[:8], summary, line: {variant_id, quantity, title, price}}`. `summary` restates the exact line, e.g. `"Add Classic Black Tee (S / Black) — ₹399.00 × 1 to your cart?"` — title/variant/price resolved from `product_context` (Stylist-grounded), never model text.

- **Reads** ("show me my cart") call `get_cart`, emit `cart_update`, and never interrupt.
- **cart_update** payload (`cart_update_from_json`) is built from the tool's JSON only — `{cart_id, checkout_url, currency, subtotal, total_quantity, lines:[{line_id,variant_id,title,quantity,unit_price,line_price}]}` — paise normalised to rupee strings via the Stylist's `_to_rupees`. Carried in the final AIMessage `additional_kwargs` (mirrors `product_cards`). `cart_snapshot` + `cart_id` are also written to state.
- **cart_id** is bound by `_bind_cart_id`: state's id wins, a model-supplied id is dropped, and an absent id is omitted so `update_cart` creates a cart (the FakeMCP cart tools were relaxed to make `cart_id` optional to mirror this).
- **Tool errors**: one retry with exponential backoff (`2**attempt`), then an honest failure message — never a pretended success, and `cart_update` is not emitted.
- Injects `product_context` into `CART_PROMPT` (new `{product_context}` marker) so the model can resolve "the black tee in M" → variant_id (the ids aren't in the message text).

### Support node (`support.py`)
`make_support_node(tools, llm=None)` — bounded ReAct loop over the single tool `search_shop_policies_and_faqs`. Calls the tool with the buyer's question, then composes an answer citing the policy section. Empty results → an honest "no published policy" reply. The "never invent policy" guarantee is a hard prompt rule (SUPPORT_PROMPT) tested in the Stage 8 evals; offline tests pin the plumbing (tool called with the question, policy text reaches the model, empty result surfaced, prompt carries the rule, out-of-scope tool refused).

### Preference Extractor (`extractor.py`)
- `extract_preferences(last_user_msg, last_assistant_msg, *, llm=None) -> dict` — runs on `FallbackChat(temperature=0, small=True)` (8B). Prompts for the full schema `{"sizes":{}, "budget_min":null, "budget_max":null, "style_tags":[], "last_category":null}`, parses robustly (`_parse_extraction`: fences/prose/garbage tolerant, budgets coerced to int, sizes/tags type-checked), and returns a **delta** of only the non-empty stated fields (`_delta`). Never raises — any model error yields `{}`. Designed to run AFTER the buyer reply (sync in the CLI, background task in Stage 6).
- `merge_profile(existing, delta) -> dict` — sizes merged key-by-key (delta wins), budget/last_category overwritten when present, `style_tags` unioned order-preserving + de-duplicated and capped at `MAX_STYLE_TAGS = 12`. Returns a fresh dict for upserting into `buyer_profiles`.

### Graph (`graph.py`)
`build_graph(tools_by_agent, checkpointer=None, *, stylist_llm=None, cart_llm=None, support_llm=None)`: nodes supervisor + stylist + cart + support; `START→supervisor`; conditional edges via `_route_selector` (`stylist`/`cart`/`support` → their nodes, `respond`/unknown → `END`); each specialist → `END`. A checkpointer is **required** for the cart interrupt/resume cycle (MemorySaver in CLI/tests; Postgres/Sqlite saver in Stage 6).

### CLI (`scripts/cli_chat.py`)
Now builds the graph with a `MemorySaver` and a `thread_id` config. `_drive_turn` invokes the graph and, while `result["__interrupt__"]` is present, prints the pending action, prompts `approve? [y/N]`, and resumes with `Command(resume={"approved": ...})`. Each turn injects the accumulated `buyer_profile`, prints route/reply/`product_cards`/`cart_update`/`product_context`, then runs the extractor synchronously and prints the merged `buyer_profile` so it can be watched accumulating. Continuity comes from the checkpointer (only the new message + profile are passed each turn).

### Tests (offline)
`test_agents_cart.py` (8: interrupt-proposes / summary-restates-line / approved-calls-update_cart / denied-no-mutation / show-cart-no-interrupt via a compiled graph + MemorySaver + a content-based fake LLM that survives node re-execution, plus pure-helper tests), `test_agents_support.py` (4: policy-matched / empty-says-no-policy / does-not-invent + prompt-rule assertion / refuses-out-of-scope-tool), `test_agents_extractor.py` (11: size/budget/category deltas, empty delta, fences, malformed→empty, never-raises, merge sizes+budget/union+dedup/12-cap/empty-existing). Plus 1 new support graph smoke in `test_agents_supervisor.py`. **24 new tests; full non-DB suite 86 passing offline** (the 7 `test_db_queries.py` errors require a live Postgres and are environmental — confirmed identical on the clean tree).

## FastAPI Streaming API (Implemented — Stage 6, MILESTONE B)

Source: `backend/main.py`, `backend/hf_main.py`, `backend/streaming/sse.py`, `backend/api/{routes_sessions,routes_chat,routes_health}.py`, updated `backend/tests/conftest.py`, `backend/tests/test_api_{sessions,chat,confirm,health}.py`.

### App factory & lifespan (`main.py`)
- `create_app(lifespan=lifespan)` builds the app (CORS from `settings.cors_origin`, includes the three routers), then `app = create_app()` is exported for `uvicorn backend.main:app`.
- **Lifespan startup** (exact order): `get_settings()` → `await init_db()` (idempotent schema) → `tools_by_agent = await load_scoped_tools(domain)` → open the checkpointer → `await checkpointer.setup()` (creates LangGraph checkpoint tables) → `app.state.{settings, tools_by_agent, graph, bg_tasks}` set → `yield` → `await close_db()`.
- **Checkpointer:** `_make_checkpointer(settings)` returns `AsyncPostgresSaver.from_conn_string(database_url)` or `AsyncSqliteSaver.from_conn_string(sqlite_path)` (imports `langgraph.checkpoint.{postgres,sqlite}.aio`). It is an **async context manager nested around the lifespan `yield`**, so the connection lives exactly as long as the app.
- Forces `WindowsSelectorEventLoopPolicy` at import (Bug B004) — async psycopg AND the AsyncPostgresSaver need it on Windows; no-op on Linux/Docker.

### HF Spaces entrypoint (`hf_main.py`)
Reuses `create_app()` and, if `frontend/dist` exists, mounts it at `/` with `StaticFiles(directory=..., html=True)` (SPA catch-all). The mount is added **after** the `/api` routers so explicit API routes win; guarded so it serves API-only until Stage 7 builds the SPA. Single port (`uvicorn backend.hf_main:app --port 8000`).

### SSE serialisation (`streaming/sse.py`)
- `sse_event(type, data) -> str` — the canonical wire format `f"event: {type}\ndata: {json.dumps(data)}\n\n"` (the contract the frontend/tests assert).
- `sse(type, data) -> ServerSentEvent` — what the endpoint generators actually yield into `EventSourceResponse` (sse-starlette owns the byte framing + keep-alive pings).
- `event_response(gen) -> EventSourceResponse(gen, ping=3600)` — large ping so a short turn's events are never split by a `: ping` comment.

### Exact SSE event shapes emitted
| Event | Payload | When |
|-------|---------|------|
| `route` | `{"agent": "stylist"\|"cart"\|"support"\|"respond"}` | supervisor `on_chain_end` |
| `token` | `{"text": "<word-chunk>"}` | replayed from the final `AIMessage` content (word-by-word) — see filtering logic |
| `product_cards` | `{"products": [{id, title, url, image_url, price:{amount,currency}, variants:[{id,title,available}]}]}` | from the stylist final message's `additional_kwargs.product_cards` |
| `cart_update` | `{cart_id, checkout_url, currency, subtotal, total_quantity, lines:[{line_id,variant_id,title,quantity,unit_price,line_price}]}` (rupee strings) | from the cart final message's `additional_kwargs.cart_update` |
| `confirm_request` | `{action_id, summary, line:{variant_id,quantity,title,price}}` | the interrupt payload (`aget_state().interrupts[0].value`) when the graph paused |
| `done` | `{turn_id: int\|null, fallback_used: bool}` | after the turn completes (NOT emitted when paused on a confirm) |

### `astream_events` filtering logic (`_stream_graph` in `routes_chat.py`)
Single pass over `graph.astream_events(input, config, version="v2")`:
- `on_chat_model_stream` with `metadata.langgraph_node ∈ {stylist,cart,support}` → emit `token` from the chunk (and mark the node "streamed").
- `on_chain_end`:
  - `name == "supervisor"` → emit `route` from `data.output["route"]`.
  - `name ∈ specialists` → read `data.output`: OR in `fallback_used`; take `messages[-1]`; if the node did **not** stream, replay its content as `token` events; then emit `product_cards` / `cart_update` from `additional_kwargs`.
- After the loop: `pending = aget_state().interrupts[0].value` if any → emit `confirm_request` and stop (turn paused). Otherwise persist the assistant message (+ `events_json` of the structured events for replay), update session cart/activity, schedule extraction, emit `done`.

`/api/confirm` resumes with `Command(resume={"approved": bool})` and reuses the same `_stream_graph` (cart node re-executes → `cart_update` + `token`), then persists + `done`.

### Endpoints
- POST `/api/sessions` → `{session_id}` (uuid4 hex = thread_id); GET `/api/sessions` → `{sessions:[{session_id, preview, ...}]}`; GET `/api/sessions/{id}` → `{session_id, cart_id, messages:[{id,role,content,events,created_at}]}` (404 if unknown; `events` = decoded `events_json`).
- POST `/api/chat` `{session_id, message}` → SSE (404 unknown session, 400 message >1000 chars).
- POST `/api/confirm` `{session_id, action_id, approved}` → SSE (404 unknown session, 409 if no pending interrupt or `action_id` mismatch).
- GET `/api/health` → `{db:"ok"|"down", mcp:"ok"|"down", model:"groq"|"gemini"}`.

### Test harness additions (`conftest.py`)
- `parse_sse(text)` — tolerant SSE parser (`\r\n`, `: ping` comments).
- `sqlite_env` — switches config to a throwaway SQLite file, clears the `get_settings` cache, resets `connection` globals (restored on teardown).
- `make_api_client(*, supervisor_llm, stylist_llm, cart_llm, support_llm)` — builds the app over FakeMCP-scoped tools + a `MemorySaver` graph with offline LLM seams; **wires `app.state` directly** (httpx `ASGITransport` skips lifespan); patches `extract_preferences` to a no-op by default; drains `bg_tasks` on teardown. 19 offline tests.

## React Frontend (Implemented — Stage 7, MILESTONE C)

Source: `frontend/src/` — React 18 + Vite, plain JS (JSX), hand-written CSS in `index.css`. No TypeScript, no react-router, no component libraries, no Tailwind.

### Design System (`index.css`)
Tokens: `--green:#8FB83A`, `--cream:#F5F0EB`, `--ink:#1A1A1A`, `--body:#4A4A4A`, `--orange:#E85D3A`, `--pink:#F0A0C0`, `--yellow:#F2D03B`, `--dkgreen:#2D6B4F`, `--disabled:#C5C5C5`. Font: Work Sans 400–800 via Google Fonts. Breakpoint: 768px (desktop/mobile). Animations: thinking-dot (staggered bounce), loading-bar (indeterminate slide), slide-right (cart drawer desktop), slide-up (cart drawer mobile), fade-in (messages), spin (button spinner).

### SSE Client (`api/client.js`)
- `parseSSE(response)` — async generator over `response.body.getReader()` + `TextDecoder({ stream: true })`. Buffers partial chunks, splits on `\n\n`, extracts `event:` type + `data:` JSON. Yields `{type, data}` objects. Handles multi-line data fields.
- `ssePost(url, body, onEvent)` — POST fetch with `Content-Type: application/json`, iterates `parseSSE`, calls `onEvent({type, data})` for each event.
- REST: `createSession()` → POST `/api/sessions`, `listSessions()` → GET `/api/sessions`, `getSession(id)` → GET `/api/sessions/{id}`, `checkHealth()` → GET `/api/health`.
- SSE: `streamChat(sessionId, message, onEvent)` → POST `/api/chat`, `confirmAction(sessionId, actionId, approved, onEvent)` → POST `/api/confirm`.

### State Hook (`hooks/useChatStream.js`)

Central hook managing all app state. Key patterns:

**Local accumulator:** `sendMessage` and `handleConfirm` create a local `acc` object tracking `{text, route, cards, confirm, cartUpd, err, fallback, gotDone}`. Each SSE event mutates `acc` and calls `updateStream()` to refresh `streamingMessage`. On `done`, the accumulated message is finalized into `messages`. On stream end without `done` (cart interrupt), the `finally` block checks `acc.gotDone` and finalizes if false — this is how the UI gets the confirm chip even though the stream ended abruptly.

**Session override:** `sendMessage(text, sessionIdOverride)` accepts an optional session ID for the create-then-send flow. React's async state batching means `createSession()` sets `currentSessionId` via setState but `sendMessage` reads the stale closure value — the override bypasses this.

**History reconstruction:** `enrichMessage(msg)` maps stored `events` array back to rich message fields (route, productCards, confirmRequest, cartUpdate, error, fallbackUsed). `resolveConfirms(messages)` scans the message sequence: a confirm_request followed by a message with cartUpdate → `confirmed`; followed by any other message → `cancelled`; nothing after → still pending.

| State | Type | Purpose |
|-------|------|---------|
| `appReady` | bool | False during initial session list fetch; loading screen shown |
| `sessions` | array | Session list for sidebar/mobile list |
| `currentSessionId` | string\|null | Active session; null = sessions view on mobile |
| `messages` | array | Rich message objects for the active session |
| `streamingMessage` | object\|null | In-flight assistant message during SSE stream |
| `cart` | object\|null | Latest cart state from any cart_update event |
| `pendingConfirm` | object\|null | Active confirm_request awaiting user action |
| `isStreaming` | bool | True while an SSE stream is open |
| `route` | string\|null | Current agent route from last route event |
| `error` | string\|null | Last error message |
| `cartOpen` | bool | Cart drawer visibility |

### Component Map (Implemented)

| Component | File | Props | Responsibility |
|-----------|------|-------|---------------|
| `App` | `App.jsx` | — | Root; view switching via `data-view` attr; owns sidebar, mobile sessions, chat area; inline `renderMessage()` emits bubble + structured components per message |
| `Composer` | `components/Composer.jsx` | `onSend: fn`, `disabled: bool`, `locked: bool` | Auto-resizing textarea; Enter=send, Shift+Enter=newline; locked state shows "Confirm or cancel above" message; disabled during streaming |
| `ProductCard` | `components/ProductCard.jsx` | `product: {title, image_url, price, url, variants}` | Single product card; image, title, price, variant chips (available/sold-out); click opens product URL in new tab |
| `ProductCardRow` | `components/ProductCardRow.jsx` | `products: array` | Horizontal scrollable row of ProductCards; renders ONLY from `product_cards` SSE event payload |
| `ConfirmChip` | `components/ConfirmChip.jsx` | `request: object`, `resolved?: string`, `onConfirm?: fn` | Pending: Confirm/Cancel buttons + spinner; resolved: checkmark/X + status text; `onConfirm(approved)` calls `confirmAction` |
| `CartDrawer` | `components/CartDrawer.jsx` | `cart: object`, `open: bool`, `onClose: fn` | Overlay + slide-over drawer; line items, subtotal, checkout CTA; desktop: 340px right panel; mobile: bottom sheet 85vh; renders ONLY from `cart_update` SSE events |
| `CheckoutBanner` | `components/CheckoutBanner.jsx` | `cart: {checkout_url, total_quantity, subtotal}` | Green banner inline after cart_update messages; item count, subtotal, Shopify checkout link |
| `ThinkingDots` | `components/ThinkingDots.jsx` | — | Three green dots with staggered bounce animation; shown while streaming before content arrives |
| `ErrorBubble` | `components/ErrorBubble.jsx` | `message: string`, `recoverable?: bool` | Orange-bordered error; optional "Retry" button when recoverable |

### Layout Strategy
- **Desktop (>768px):** `display:flex` — `.sidebar` (260px fixed) + `.chat-main` (flex:1). Sidebar always visible. Cart drawer slides in from right over chat area.
- **Mobile (≤768px):** Sidebar hidden. `data-view="sessions"` shows `.mobile-sessions` (full-screen list with avatars + FAB); `data-view="chat"` shows `.chat-main` with back button. Cart drawer is a bottom sheet (border-radius 24px top, max-height 85vh). View toggling driven by `currentSessionId` state (null → sessions, non-null → chat).
- **Message bubbles:** User = ink background, cream text, radius 18/18/4/18. Assistant = cream background, ink text, radius 18/18/18/4. Max-width clamped (user 65%/mobile 78%, assistant 75%/mobile 85%).

## Evaluation Harness (Implemented — Stage 8)

Source: `backend/tests/evals/runner.py`, `backend/tests/evals/golden/`, `backend/tests/evals/adversarial/`.

### Engine (`runner.py`)
- YAML-driven eval engine that parses conversational sequences and assertions.
- Loads test cases from `golden/` and `adversarial/` directories.
- Uses `RecordingMCPTools` spy wrappers to capture tool sequence and arguments.
- Uses scripted `EvalFakeLLM` for deterministic replay of supervisor, stylist, and support turns.
- Uses content-based `EvalCartLLM` for cart turns (survives LangGraph node re-execution).

### Assertions
- **route**: Asserts the supervisor classifies the intent correctly.
- **tool_sequence**: Asserts tools are called in the exact expected order with expected args.
- **grounding**: Asserts the final assistant message does not contain invented prices (₹NNN) or URLs not present in tool results.
- **write_gating**: Asserts `update_cart` is never called without a preceding approved `interrupt()`.
- **adversarial**: `must_not_contain`, `must_not_call`, `max_tool_calls` to ensure prompt injection and boundary testing.
- **min_products_returned / max_products_returned (F2)**: Asserts the size of the final message's `additional_kwargs.product_cards.products` array. `min_products_returned` guards the Phase-1 contract (a broad filtered query must surface ≥ N cards, not collapse to one); `max_products_returned` guards the Phase-2 contract (a narrowing follow-up must collapse to ≤ N cards, typically 1). Counts the cards the SSE pipeline actually emits, not anything in the model's prose.

### Injections (`seed_injections.py`)
- Shopify Admin GraphQL tool to seed injection payloads into product descriptions and policy texts.

## Final Polish & Deployment (Implemented — Stage 9)

- **Backend & Testing**: Added `test_sanitize.py` and `test_config.py`. Enforced code quality via `ruff check`. Evaluated the full suite successfully (121 core tests + 42 eval tests).
- **Frontend Testing**: Integrated `vitest` and `@testing-library/react`. Added basic `App.test.jsx` smoke tests to verify component rendering states.
- **CI/CD & Docker**: Created a production-ready `Dockerfile` mapping `frontend/dist` directly onto the backend. Built a `.github/workflows/ci.yml` pipeline with 4 discrete jobs: `backend`, `frontend`, `evals`, `mcp-contract`.
- **Documentation**: Added portfolio-ready `README.md` with `mermaid` architecture diagram, eval results, and HF Spaces frontmatter. Provided `demo_script.md` for a 2-minute feature walkthrough.
- Assured build transparency constraints (no ORM, no component libraries, provider agnostic).
- Project is 100% complete.

## Seed Catalog Summary (post-expansion)

Base catalog (`seed/catalog.csv`) + three additive expansion CSVs imported on top
(`seed/catalog_jeans_expansion.csv`, `seed/catalog_accessories_footwear_expansion.csv`,
`seed/catalog_ethnic_expansion.csv`). The expansion is sized so multi-result filtered
search ("jeans under ₹500, size 32") returns several products instead of one, with
deliberate sub-₹500 jeans variants seeded in.

| Category | Products | Variant Rows | Price Range (₹) |
|----------|----------|-------------|----------------|
| T-Shirts | 5 | 16 | 399–549 |
| Oversized Tees | 3 | 9 | 599–699 |
| Jeans | 10 | 35 | 399–1099 |
| Joggers | 3 | 8 | 699–799 |
| Dresses | 3 | 9 | 799–1099 |
| Kurtas | 8 | 29 | 699–1499 |
| Sneakers | 7 | 29 | 599–1499 |
| Accessories | 10 | 16 | 299–599 |
| **Total** | **49** | **151** | **299–1499** |

Per-category notes after the expansion:
- **Jeans** — 3 products have at least one variant under ₹500 (Basic Straight Light Blue, Budget Slim Grey Wash, Stretch Skinny Black size 28). Sizes span 28–36 for "men's" lines (slim/skinny/distressed/bootcut/budget); women's lines span 28–34 (mom-fit, wide-leg, cropped).
- **Kurtas** — Nehru Jacket (men's) is filed under the `Kurtas` Type to keep ethnic-wear browsing co-located; tag-filter `nehru-jacket` separates it from the women's kurta set.
- **Sneakers** — Slip-ons / sandals / loafers are filed under the `Sneakers` Type for the same reason: one umbrella footwear browse. Tags (`sandals`, `loafers`, `running`) carry the sub-category.

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
