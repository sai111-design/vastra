# Progress Tracker — Vastra

## Current Status
- **Last completed stage:** 9 — Bug fixes + polish. **Project Complete**. Added portfolio-ready documentation, architecture diagrams, HF Spaces frontmatter, and demo script.
- **Next stage:** None (Completed)
- **Blockers:** None

## Changelog

### 2026-06-18 — Stage 9: Polish & Portfolio Ready
- ✅ **Backend & Eval Polish**: Fixed all ruff formatting errors via `ruff check --fix`. Added `test_sanitize.py` and `test_config.py`. Eval suite passes 100% on all 42 scenarios. Full core suite passes with 121 tests.
- ✅ **Frontend Polish**: Integrated Vitest and React Testing Library. Added `App.test.jsx` for critical component smoke testing.
- ✅ **Ops**: Created a multi-stage `Dockerfile` (Node 20 frontend + Python 3.11 backend serving on port 8000). Created `.github/workflows/ci.yml` CI pipeline with 4 parallel jobs (`backend`, `frontend`, `evals`, `mcp-contract`).
- ✅ **Documentation**: `README.md` updated with HF Spaces frontmatter, mermaid architecture diagram, eval results, build transparency constraints, and quick start deployment instructions.
- ✅ `demo_script.md` created with a tight 2-minute walkthrough covering discovery, cart write-gate, support, memory extraction, and checkout handoff.
- ✅ `Agent/progress.md` and `Agent/implementations.md` updated to reflect the final 100% complete state.

### 2026-06-18 — Stage 8: Evaluation Harness
- ✅ backend/tests/evals/runner.py — YAML-driven eval engine: loads test cases from `golden/` and `adversarial/` directories, replays conversations through the compiled graph using `RecordingMCPTools` spy wrappers + `EvalFakeLLM`/`EvalCartLLM` scripted fixtures, asserts per-turn: route (supervisor routed correctly), tool sequence (tools called in order with expected args), grounding (no ₹ prices or URLs not in tool results), write-gating (update_cart never without approved interrupt), adversarial (must_not_contain, must_not_call, max_tool_calls). `format_summary()` renders a markdown table for CI output.
- ✅ backend/tests/evals/golden/ — 30 YAML conversation files: basic discovery (4 — color/category/budget/size), multi-turn refinement (3 — cheaper/color/formal), positional reference (2 — "the second one"/"that one"), cart add+confirm (2), cart add+cancel (2 — incl. must_not_call write-gating), show cart/checkout (2), policy questions (3 — returns/shipping/sizing), mixed flows (3 — browse→policy→cart, browse→cart→view, full journey), greetings (2 — pure/with-request), budget+profile (2), edge cases (5 — empty results, product details, goodbye, product care→stylist routing, desire-not-cart)
- ✅ backend/tests/evals/adversarial/ — 10 YAML files: prompt injection via product description, injection via policy text, off-topic pressure, impossible negative price, out-of-stock variant, cart without browsing context, double confirm, excessive tool calls (cap assertion), unicode/homoglyph injection, multiline injection. All use `AdversarialFakeMCPTools` with injection strings in tool results.
- ✅ backend/tests/evals/test_golden.py — pytest parametrized over 30 golden YAMLs + suite-level meta-test (`test_golden_suite_pass_rate`) asserting ≥90% case-level pass rate
- ✅ backend/tests/evals/test_adversarial.py — pytest parametrized over 10 adversarial YAMLs + suite-level meta-test (`test_adversarial_suite_100_percent`) asserting 100% pass rate (zero tolerance for safety failures)
- ✅ backend/tests/conftest.py — added `AdversarialFakeMCPTools(FakeMCPTools)` (injection-laden search/policy responses), `OutOfStockFakeMCPTools(FakeMCPTools)` (all variants `available: false`), 5 injection payload constants (`INJECTION_PRODUCT_DESC`, `INJECTION_POLICY_TEXT`, `INJECTION_UNICODE`, `INJECTION_MULTILINE`, `INJECTION_ADMIN_COMMAND`) — same strings as `seed_injections.py`
- ✅ scripts/seed_injections.py — complete Shopify Admin GraphQL implementation: `--inject` plants 5 injection payloads into product descriptions, `--restore` reverts from JSON backup, `--list` shows current status. Uses `httpx` + Admin `productUpdate` mutation.
- ✅ requirements.txt — added `pyyaml>=6.0` for eval YAML loading
- ✅ Full suite **148 passed, 7 errored** (the 7 are the pre-existing Postgres-only `test_db_queries.py` — environmental, no live PG on the box); 42 eval tests (30 golden + 10 adversarial + 2 meta) all passing
- ⚠️ Eval harness tests the agent PIPELINE (routing, tool calling, sanitisation, grounding enforcement), not the LLM's generation quality — scripted FakeLLM responses mean prompts are not under test. This is the right trade-off for CI (deterministic, fast, no API costs).
- ⚠️ Grounding assertion checks ₹NNN prices (with paise↔rupee equivalence) and URLs against tool results; does NOT check product names (fuzzy matching would be brittle). A price like ₹399 passes if 39900 (paise), 399, 399.0, or 399.00 appears in any tool result.
- ⚠️ Cart eval turns use a content-based `EvalCartLLM` (not a scripted sequence) to survive LangGraph's node re-execution on interrupt resume. The LLM checks for write verbs (add/remove/delete/update/change) before read keywords (show/what's in/checkout) to avoid false routing.

### 2026-06-16 — Stage 6: FastAPI Streaming API (MILESTONE B)
- ✅ backend/streaming/sse.py — `sse_event(type, data)` (canonical wire string per spec), `sse(type, data)` → sse-starlette `ServerSentEvent` (what the generators actually yield), `event_response(gen)` → `EventSourceResponse(gen, ping=3600)` (large ping so keep-alives never split a short turn), event-name constants
- ✅ backend/main.py — `create_app(lifespan=lifespan)` factory + `app = create_app()`; lifespan: `init_db()` → `load_scoped_tools()` → open `AsyncPostgresSaver`/`AsyncSqliteSaver` via `from_conn_string` (async CM nested around `yield`) → `checkpointer.setup()` → `build_graph(...)` → stash `settings`/`tools_by_agent`/`graph`/`bg_tasks` on `app.state`; CORS from `settings.cors_origin`; forces `WindowsSelectorEventLoopPolicy` at import (Bug B004 — async psycopg/PostgresSaver)
- ✅ backend/api/routes_sessions.py — POST `/api/sessions` (uuid4 hex = thread_id), GET `/api/sessions` (preview list), GET `/api/sessions/{id}` (messages + parsed replay events; 404 if unknown)
- ✅ backend/api/routes_chat.py — POST `/api/chat` (SSE): validate session (404) + message ≤1000 chars (400), load buyer_profile from DB, persist user message up front, stream `astream_events(version="v2")` → `route`/`token`/`product_cards`/`cart_update`, detect interrupt via `aget_state().interrupts` → `confirm_request` (stream ends, no `done`), else persist assistant message + events_json, fire-and-forget Preference Extractor, emit `done {turn_id, fallback_used}`. POST `/api/confirm` (SSE): validate session (404) + matching pending `action_id` (409 if stale/resolved/mismatched), resume via `Command(resume={"approved": bool})`, stream `cart_update`/`token`, persist, emit `done`
- ✅ backend/api/routes_health.py — GET `/api/health` → `{db, mcp, model}`: DB `SELECT 1`; MCP = startup tool-load signal (`app.state.tools_by_agent["stylist"]` non-empty); model = `groq` unless no key → `gemini`
- ✅ backend/hf_main.py — reuses `create_app()`, mounts `frontend/dist` at `/` with `StaticFiles(html=True)` SPA catch-all (added LAST so it never shadows `/api`); guarded — serves API-only until Stage 7 builds the SPA
- ✅ backend/tests/conftest.py — added `parse_sse()` (tolerant of `\r\n` + ping comments), `sqlite_env` (throwaway SQLite + cache/global reset), `make_api_client` factory (ASGITransport app over FakeMCP + MemorySaver graph with offline LLM seams; extractor patched to no-op by default; drains bg tasks on teardown)
- ✅ backend/tests/test_api_sessions.py (5), test_api_health.py (3), test_api_chat.py (6: stream shape, 404, 400, history persist, **two-turn checkpoint share**, **extractor updates profile**), test_api_confirm.py (5: approve→cart_update, deny→unchanged, stale→409, wrong-id→409, unknown-session→404) = **19 new tests, all pass offline**
- ✅ Full suite **106 passed, 7 errored** (the 7 are the pre-existing Postgres-only `test_db_queries.py` — environmental, no live PG on the box); ruff clean
- ⚠️ **No `on_chat_model_stream` events fire**: the agent nodes invoke the LLM via `ainvoke` (Stage 4/5 design), and the offline `FakeLLM` is not a LangChain Runnable — so `astream_events` emits no token chunks. `token` events are **synthesised by replaying the grounded final `AIMessage` content** (word-chunked). This is also safer: raw model streaming would leak the supervisor's route JSON and the stylist's intermediate ReAct turns. A genuine `on_chat_model_stream` (future streaming model) is passed through and suppresses the replay for that node
- ⚠️ `product_cards`/`cart_update` are read from the final message's `additional_kwargs` (surfaced in the node's `on_chain_end` output), never parsed from text — same grounding contract as the agents
- ⚠️ On a cart interrupt, `/api/chat` emits `confirm_request` and the stream ENDS with **no `done`** (turn paused); `/api/confirm` emits the eventual `cart_update` + `done`. The pending action is read from `aget_state().interrupts[0].value` (it rides the interrupt payload, not checkpointed state — Stage 5 note)
- ⚠️ Preference Extractor runs as a true `asyncio.create_task` AFTER the reply is fully streamed (tracked in `app.state.bg_tasks` so tests can await it); `done` does not wait on it. A bare "respond"/greeting turn (no reply text) is not persisted as an empty assistant bubble

### 2026-06-18 — Stage 7: React 18 Frontend (MILESTONE C)
- ✅ frontend/index.html — Google Fonts preconnect + Work Sans 400–800, favicon, meta viewport
- ✅ frontend/src/main.jsx — React 18 StrictMode entry, imports App + index.css
- ✅ frontend/src/api/client.js — SSE client using fetch + ReadableStream + TextDecoder; `parseSSE()` async generator (handles partial chunks, buffering, multi-line events); `ssePost(url, body, onEvent)` drives streaming endpoints; REST helpers: `createSession()`, `listSessions()`, `getSession()`, `checkHealth()`; SSE helpers: `streamChat()`, `confirmAction()`
- ✅ frontend/src/hooks/useChatStream.js — Central state hook. Local accumulator pattern in `sendMessage`/`handleConfirm` for streaming; cart interrupt handling (if stream ends without `done`, finally block finalises accumulated message); `enrichMessage()` reconstructs rich messages from stored events on session load; `resolveConfirms()` scans message sequence to determine confirm resolution from history; `sendMessage(text, sessionIdOverride)` accepts optional session ID for create-then-send timing (React async batching workaround); returns 17 values: `appReady`, `sessions`, `currentSessionId`, `messages`, `streamingMessage`, `cart`, `pendingConfirm`, `isStreaming`, `route`, `error`, `cartOpen`, `createSession`, `openSession`, `sendMessage`, `confirmAction`, `toggleCart`, `goBack`, `clearError`
- ✅ frontend/src/App.jsx — Root component; view switching via `data-view` attribute + CSS media queries; desktop: sidebar always visible + chat area; mobile: either session list OR chat view; loading screen with animated progress bar; empty chat state with example prompt chips; inline `renderMessage()` returns array of JSX per message (bubble + product cards + confirm chip + checkout banner); auto-scroll on new messages; session list with relative timestamps and deterministic avatar colors
- ✅ frontend/src/components/ThinkingDots.jsx — Three green animated dots with staggered keyframes
- ✅ frontend/src/components/ErrorBubble.jsx — Orange-bordered error with optional retry button
- ✅ frontend/src/components/ProductCard.jsx — Image, title, price, variant chips (available/sold-out with line-through); opens product URL on click
- ✅ frontend/src/components/ProductCardRow.jsx — Horizontal scrollable row of ProductCards
- ✅ frontend/src/components/ConfirmChip.jsx — Pending state: Confirm/Cancel buttons + loading spinner; resolved state: checkmark/X icon with status text; plain text rendering (no dangerouslySetInnerHTML)
- ✅ frontend/src/components/CheckoutBanner.jsx — Green banner with title, item count, subtotal, Shopify checkout link
- ✅ frontend/src/components/CartDrawer.jsx — Overlay + drawer panel; line items with title/quantity/price; subtotal; checkout CTA; trust copy; empty cart state; desktop: right slide-over 340px; mobile: bottom sheet with 24px border-radius top
- ✅ frontend/src/components/Composer.jsx — Auto-resizing textarea; send button; disabled/locked states; Enter to send, Shift+Enter for newline; lock message when confirm pending
- ✅ frontend/src/index.css (~1060 lines) — Complete design system: CSS variables (all 8 design tokens), reset, animations (thinking-dot, loading-bar, slide-right, slide-up, fade-in, spin), cold start screen, app layout (flex sidebar + main), sidebar (260px), chat header/message list/bubbles (user: ink bg rounded 18/18/4/18; assistant: cream bg rounded 18/18/18/4), product cards (16px border-radius, 1.5px border, horizontal scroll on mobile), variant chips, confirm chip + resolved state, cart drawer, checkout banner, composer, thinking dots, error bubble, mobile session list with avatars + FAB; responsive at 768px breakpoint
- ✅ frontend/public/assets/vastra-mark-v2.png — Logo from design bundle
- ✅ frontend/public/assets/vastra-intro.mp4 — Intro video from design bundle
- ✅ Production build: `npx vite build` → 41 modules, 0 errors (dist/index.html 0.71KB, dist/assets/index.css 16.55KB, dist/assets/index.js 162.06KB)
- ✅ Visual verification: desktop layout confirmed in Chrome at localhost:5173 — sidebar, brand header, "+ New conversation" button, empty state with logo/title/prompt chips all rendering correctly; loading screen with animated progress bar confirmed; Work Sans font and cream/green/ink color scheme matching design spec
- ⚠️ Mobile viewport testing limited — Chrome window resize couldn't shrink below ~1600px inner width on the dev machine; CSS media queries at 768px breakpoint structurally verified (sidebar hidden, mobile-sessions flex, cart as bottom sheet, product cards sized for small screens)
- ⚠️ End-to-end golden path (send message → streaming → product cards → confirm → cart drawer) not testable without the backend running; all SSE parsing and state management logic verified via code review and build compilation
- ⚠️ No SSE parsing bugs found; no layout bugs found in desktop visual verification

### 2026-06-15 — Stage 5: Cart + Support + Preference Extractor
- ✅ backend/agents/prompts.py — filled CART_PROMPT (write-gate rule, restate-exact-line, summarise-from-tool-payload-only, `{product_context}` marker, splices `TOOL_DATA_INSTRUCTION`), SUPPORT_PROMPT (answer ONLY from policy tool, name the section, explicit no-policy fallback, invention strictly prohibited), EXTRACTOR_PROMPT (exact JSON schema, explicit-only extraction, no inference from product views); bumped `PROMPT_VERSION` → "2026-06-15.1"; added `PRODUCT_CONTEXT_MARKER`
- ✅ backend/agents/cart.py — `make_cart_node`: bounded ReAct loop with the `interrupt()` write-gate. update_cart → build `pending` (action_id/summary/line restating title·variant·price·qty from product_context) → `interrupt(pending)` → on `{"approved": True}` only, run update_cart (one retry + exp backoff, honest failure never a fake success) and emit `cart_update` from tool JSON; on deny → "cart unchanged", no tool call. get_cart ("show my cart") emits cart_update with no interrupt. `_bind_cart_id` injects state's cart_id (or omits for a new cart; model ids dropped)
- ✅ backend/agents/support.py — `make_support_node`: bounded ReAct loop over `search_shop_policies_and_faqs`; cites the section; empty results → honest no-policy reply; out-of-scope tool refused (support can't reach catalog/cart)
- ✅ backend/agents/extractor.py — `extract_preferences(...,*,llm=None)` on the 8B model (temp 0), robust JSON parse → non-empty-fields delta, never raises (errors → `{}`); `merge_profile` (sizes merge, budget/category overwrite, style_tags union+dedup capped at 12)
- ✅ backend/agents/graph.py — wired cart + support; `_route_selector` (specialists → nodes, respond/unknown → END); `cart_llm`/`support_llm` test seams; checkpointer now REQUIRED for the cart interrupt cycle
- ✅ backend/agents/stylist.py — enriched `product_context` entries with `price` + per-variant `{id,title}` (kept `variant_ids`) so the Cart agent can restate the exact line
- ✅ scripts/cli_chat.py — MemorySaver checkpointer + thread_id; `_drive_turn` resolves cart interrupts via Y/N → `Command(resume=...)`; prints product_cards/cart_update/product_context; runs the extractor synchronously post-turn and prints the accumulating buyer_profile
- ✅ backend/tests/test_agents_cart.py (8), test_agents_support.py (4), test_agents_extractor.py (11) + 1 support graph smoke in test_agents_supervisor.py = **24 new tests**; cart interrupt paths driven through a compiled graph + MemorySaver with a content-based fake LLM (survives node re-execution)
- ✅ backend/tests/conftest.py — relaxed FakeMCP `get_cart`/`update_cart` to make `cart_id` optional (mirrors live create-cart-on-absent)
- ✅ Updated test_agents_supervisor.py — the Stage-4 "unwired cart route ends cleanly" test became "routes cart through cart node" (cart is now wired)
- ✅ Full non-DB suite **86 passing offline**; verified end-to-end offline: discovery → product_context → cart add → interrupt summary "Add Classic Black Tee (S / Black) — ₹399.00 × 1 to your cart?" → approve → cart_update (₹1197.00) / deny → "cart unchanged"
- ⚠️ `pending_action` is surfaced in the **interrupt payload** (`result["__interrupt__"][0].value`), not checkpointed state — a node that interrupts never returns, so it cannot also write state. The denied/approved-complete returns DO write `pending_action: None`. Stage 6 reads the interrupt payload to emit `confirm_request`
- ⚠️ The cart node's LLM-before-interrupt **runs twice** (LangGraph re-executes the node on resume) — relied on temperature-0 determinism; the only mutation is post-approval
- ⚠️ 7 `test_db_queries.py` tests error without a live Postgres (environmental — proven identical with Stage-5 changes stashed); all Stage-5 tests pass offline

### 2026-06-12 — Stage 4: Supervisor + Stylist Agent (MILESTONE A)
- ✅ backend/agents/state.py — `VastraState(MessagesState)` with session_id, buyer_profile, product_context, cart_id, cart_snapshot, pending_action, route, fallback_used, turn_count; cart fields reserved now so Stage 4 checkpoints stay compatible with Stage 5
- ✅ backend/agents/prompts.py — versioned constants (`PROMPT_VERSION = "2026-06-12.1"`): SUPERVISOR_PROMPT (4-route JSON classification w/ cart-verb rule, ambiguity→stylist, greeting+request routes by request), STYLIST_PROMPT (≤4 picks, empty-results drop-weakest-constraint-retry-once-then-clarify, per-tool price-unit guidance, 1 tool-call example, splices `TOOL_DATA_INSTRUCTION`), SUPPORT/CART/EXTRACTOR placeholders for Stage 5; `{buyer_profile}` marker injected via `.replace()` (prompts are full of JSON braces — `.format()` would need escaping everywhere)
- ✅ backend/agents/supervisor.py — async `supervisor_node` (FallbackChat temp 0 via lazy `_get_llm()` singleton, patched in tests), `parse_route()` (bare JSON → code-fence strip → regex scan → default "stylist"), `trim_messages(messages, budget)` (keeps leading SystemMessage + newest messages, drops oldest-middle, always keeps the newest even over budget; ~4 chars/token estimate), increments turn_count
- ✅ backend/agents/stylist.py — `make_stylist_node(tools, llm=None)`: bounded ReAct loop counting **executed tool calls** (≤ MAX_TOOL_CALLS_PER_TURN, mid-response cutoff for parallel calls, dangling tool_calls answered then one forced final text reply); every result through `sanitize_tool_output()`; `build_product_cards()` from raw tool JSON only (per-tool extractors for the two live shapes, details **merges** into search cards without losing variant ids); product_context replaced when products shown; intra-turn scratchpad NOT written to state (small checkpoints, no dangling tool_calls poisoning next turn)
- ✅ backend/agents/graph.py — `build_graph(tools_by_agent, checkpointer=None, *, stylist_llm=None)`; `_route_or_end` maps unwired-but-legal routes (cart/support/respond) to END so a valid classification can't crash the Stage 4 graph (deviation from the task's raw `lambda s: s["route"]`, which would KeyError on cart/support)
- ✅ backend/llm/fallback.py — added `FallbackChat.bind_tools(tools)` binding both primary and fallback models (agents stay provider-free per rules.md)
- ✅ scripts/cli_chat.py — MILESTONE A harness: loads live scoped tools, builds graph (no checkpointer), REPL printing route/turn/fallback flag, assistant text, full product_cards payload, and product_context; continuity via result-state echo
- ✅ backend/tests/test_agents_supervisor.py — 19 tests: 4 routing intents, malformed→stylist default, profile injection, turn_count, parse_route variants (fences/prose/unknown route/non-object), trim_messages (under-budget/middle-drop/oversized-newest/empty), 3 compiled-graph smoke tests (stylist path, respond ends w/o specialist, unwired cart route ends cleanly)
- ✅ backend/tests/test_agents_stylist.py — 14 tests: FakeMCP tool calls + loop termination, sanitiser fencing, profile injection, cap enforcement (serial + mid-parallel-response), unknown tool error, cards-from-tool-JSON (ids/urls/images/price normalization/availability), cards-ignore-model-text, details-merge keeps variants, ≤4 cards, malformed-JSON skip, B009 content-block regression, product_context update/no-op, fallback_used propagation
- ✅ backend/tests/conftest.py — search_catalog + get_product_details canned shapes **re-recorded from the live store** (Stage 3's inferred shapes were wrong — see Assumptions); FakeLLM upgraded: scripted `responses` list (last repeats), `calls` recording, `bind_tools` no-op
- ✅ Full suite 68/68 (26 Stage 3 + 8 DB + 34 Stage 4); agent tests fully offline
- ✅ MILESTONE A verified live: "show me black t-shirts under 600" → route=stylist → live search_catalog → "The Classic Black Tee (₹399)…" + product_cards (real GID/URL/CDN image/₹399.00 INR/4 variants); "return policy" → support; "add the black tee to my cart" → cart; "thanks!" → respond
- ⚠️ Routes cart/support/respond end at the supervisor with no assistant message in Stage 4 (nodes land in Stage 5); CLI prints an explicit note for those turns
- ⚠️ product_cards payload travels in the final AIMessage's `additional_kwargs` (not a state key) — keeps VastraState exactly as specced and binds the payload to the message for history replay
- ⚠️ Card price amounts are normalised to **major-unit strings** ("399.00") at extraction; the Stage 1 "frontend divides by 100" note is superseded (units differ per tool — see implementations.md)
- 🐛 Fixed: B009 (below) — live adapter tools return MCP content-block lists, not strings

### 2026-06-11 — Stage 3: MCP Tool Layer + LLM Fallback

### 2026-06-11 — Stage 3: MCP Tool Layer + LLM Fallback
- ✅ backend/mcp/client.py — `load_scoped_tools(store_domain)` loads tools from Storefront MCP and partitions by `SCOPES` (stylist/cart/support); logs discovered tool names at INFO; warns on missing tools; transport-candidate loop (`streamable_http` → `http` → `sse`) for adapter-version resilience
- ✅ backend/mcp/sanitize.py — `sanitize_tool_output()` wraps any string in `<tool_data>` delimiters; `wrap_tool_call()` decorator (sync + async, coerces non-str); `TOOL_DATA_INSTRUCTION` constant referenced by every system prompt
- ✅ backend/llm/fallback.py — `FallbackChat` (Groq primary, 1 retry on rate-limit w/ exponential backoff, transparent Gemini Flash failover) + `FallbackChatStreaming` (`.astream()` variant, pre-first-chunk failover only); both expose `.fallback_used`
- ✅ backend/tests/conftest.py — `FakeMCPTools` (5 tools as real `StructuredTool`s w/ canned JSON recorded from Stage 1 spike), `fake_scoped_tools` fixture (same `dict[str,list]` shape as loader), `fake_llm` fixture (`FakeLLM` with `ainvoke`/`astream`)
- ✅ backend/tests/test_mcp_client.py — 14 tests (scopes, partition, transport URL, missing-tool warning, http-transport fallback, sanitiser, injection containment, decorator)
- ✅ backend/tests/test_llm_fallback.py — 11 tests (model selection, happy path, retry, rate-limit/connection failover, `fallback_used` flag, streaming + streaming failover)
- ✅ 26 Stage-3 tests pass; full suite 34/34 (incl. 8 pre-existing DB tests)
- ✅ requirements.txt — added `groq>=0.11` (we import `groq.RateLimitError`/`groq.APIConnectionError` directly; transitive via langchain-groq but now explicit)
- ⚠️ SCOPES uses verified tool name `search_catalog` (NOT the PRD/task-snippet's `search_shop_catalog`) — consistent with the Stage 1 correction; union of scopes = the 5 verified tools
- ⚠️ Task snippet said Groq raises `openai.RateLimitError`; actually `langchain-groq` ≥1.x uses the `groq` SDK with its own `groq.RateLimitError`/`groq.APIConnectionError` (and `openai` is not even installed). Caught the `groq` classes.
- 🐛 Fixed: `backend/mcp/` package shadowed the installed top-level `mcp` package under pytest's prepend import mode (B008)

### 2026-06-11 — Stage 2: Database Foundation & Config
- ✅ backend/config.py — Settings(BaseSettings) over all .env vars; DB_BACKEND literal; cached get_settings() singleton; validators (SHOPIFY_STORE_DOMAIN non-empty, DATABASE_URL required for postgres)
- ✅ backend/db/schema.sql — 4 tables (sessions, messages, buyer_profiles, tool_call_log) + 2 indexes, verbatim from PRD
- ✅ backend/db/connection.py — psycopg AsyncConnectionPool (postgres) + aiosqlite (sqlite) behind get_conn(); init_db() with SQLite DDL translation; graceful connection errors; close_db()
- ✅ backend/db/queries.py — all 10 query functions, fully parameterised (zero string interpolation), results as dicts
- ✅ backend/tests/test_db_queries.py — 8 tests, all passing (7 Postgres + 1 full SQLite-translation round-trip)
- ✅ init_db() verified idempotent (ran twice, no errors); all 4 tables confirmed with correct columns/types
- ✅ requirements.txt — added psycopg-pool, aiosqlite (directly imported; documented in implementations.md)
- ⚠️ Host Postgres port moved 5432 → 55432 (docker-compose.yml, .env, .env.example) to avoid two native PostgreSQL services (v13 on 5432, v18 on 5433) on the dev machine
- ⚠️ docker-compose.yml frontend service given `image: node:20-alpine` so the compose file validates (was missing image/build context, blocking `docker compose up postgres`)
- ⚠️ now() translated to CURRENT_TIMESTAMP for SQLite (a bare function call is invalid in a SQLite DEFAULT clause)

### 2026-06-11 — Stage 1: Shopify Dev Store & MCP Spike
- ✅ seed/catalog.csv — 75 variant rows across 26 products; imported into Shopify admin
- ✅ seed/policies/returns.md — 7-day return/exchange policy
- ✅ seed/policies/shipping.md — free shipping ≥₹999, standard/express tiers, COD
- ✅ seed/policies/size-guide.md — measurement tables for all categories with fit notes
- ✅ scripts/verify_mcp.py — MCP spike passes all 3 steps (initialize, tools/list, test search)
- ✅ scripts/seed_injections.py — placeholder for Stage 8
- ✅ MCP endpoint verified: storefront-renderer v0.1.0, protocol 2025-03-26, 5 tools confirmed
- ✅ Test search for "black t-shirt" returned Classic Black Tee with variants, prices, images
- ⚠️ Tool name deviation: Shopify uses `search_catalog` not `search_shop_catalog` — PRD assumption corrected
- ⚠️ Prices in minor units (paise): ₹399 returned as `39900` — frontend must divide by 100
- 🐛 Fixed: Windows cp1252 terminal encoding crash — added UTF-8 reconfigure for stdout/stderr
- 🐛 Fixed: Dev store password protection caused 401 — must disable under Online Store → Preferences

### 2026-06-11 — Stage 0: Agent Scaffolding
- ✅ Created project skeleton with all directories and placeholder files
- ✅ Initialized Agent/ folder with rules, context, implementations, progress
- ✅ docker-compose.yml, requirements.txt, package.json, .env.example, .gitignore
- 📋 Notes: No implementation code yet — all files are docstring placeholders

---

## Bug Log
| ID | Description | Found In | Status | Resolved In |
|----|-------------|----------|--------|-------------|
| B001 | Windows cp1252 terminal can't render ✓/✗/⚠ Unicode symbols | Stage 1 verify_mcp.py | ✅ Fixed | Stage 1 — added sys.stdout.reconfigure(encoding="utf-8") |
| B002 | Dev store password protection returns 401 on /api/mcp | Stage 1 verify_mcp.py | ✅ Fixed | Stage 1 — disable password under Online Store → Preferences |
| B003 | search_shop_catalog tool not found (actual name: search_catalog) | Stage 1 verify_mcp.py | ✅ Fixed | Stage 1 — updated script to use correct tool name |
| B004 | psycopg async fails on Windows ProactorEventLoop ("cannot use the 'ProactorEventLoop'") | Stage 2 connection.py | ✅ Fixed | Stage 2 — force WindowsSelectorEventLoopPolicy in tests/conftest.py (Stage 6 main.py must do the same for local Windows runs; non-issue in Linux Docker) |
| B005 | Auth "password authentication failed for user vastra" — native PostgreSQL (v13/v18) shadowing host ports 5432/5433 | Stage 2 | ✅ Fixed | Stage 2 — published container on host port 55432 |
| B006 | SQLite "near \"(\": syntax error" — bare datetime('now') invalid in a DEFAULT clause | Stage 2 connection.py | ✅ Fixed | Stage 2 — translate now() → CURRENT_TIMESTAMP for SQLite |
| B007 | `docker compose up postgres` failed: frontend service had no image/build context | Stage 2 docker-compose.yml | ✅ Fixed | Stage 2 — added image: node:20-alpine to frontend service |
| B008 | `ImportError: cannot import name 'ClientSession' from 'mcp'` under pytest — local `backend/mcp/` package shadowed the installed `mcp` package because pytest (prepend import mode) put `backend/` on sys.path (no `backend/__init__.py`) | Stage 3 conftest.py / client.py | ✅ Fixed | Stage 3 — added `backend/__init__.py` so the test basedir is the project root, not `backend/`; `from mcp import …` now resolves to the installed package |
| B009 | Stylist extracted 0 product cards from the LIVE store while offline tests passed. langchain-mcp-adapters tools (`response_format="content_and_artifact"`) return a **list of MCP content blocks** `[{"type":"text","text":"<json>"}]` from `.ainvoke()`, not a plain JSON string like FakeMCP's StructuredTools. `str(list)` produced a Python repr that broke `json.loads`. | Stage 4 stylist.py (live CLI) | ✅ Fixed | Stage 4 — added `_content_to_text()` to flatten content-block lists before sanitise/extract; offline regression test added (`test_live_adapter_content_block_results_are_flattened`) |
| B010 | Cart node forced `args["cart_id"] = None` for a brand-new cart, sending an explicit null to `update_cart`. The strict FakeMCP `update_cart(cart_id: str)` (and likely the live tool) rejects a null for a required `cart_id`, so a first add failed with a validation error and fell to the honest-failure path (no `cart_update`). | Stage 5 cart.py (integration smoke) | ✅ Fixed | Stage 5 — `_bind_cart_id` injects cart_id only when present and otherwise omits it (live create-cart-on-absent); FakeMCP `get_cart`/`update_cart` relaxed to optional `cart_id` |
| B011 | (Design note, not a defect) LangGraph re-runs the whole cart node on `Command(resume=...)`, so a call-count-indexed FakeLLM diverges across the resume re-execution. | Stage 5 test_agents_cart.py | ✅ Handled | Stage 5 — cart tests use a **content-based** fake LLM (decides from the message window) that replays identically on the re-run |
| B012 | `astream_events(version="v2")` emitted ZERO `on_chat_model_stream` events, so naive token streaming produced nothing. Cause: the agent nodes call the LLM via `ainvoke` (not `astream`), and the offline `FakeLLM` is not a LangChain Runnable, so no chat-model stream callbacks fire. | Stage 6 routes_chat.py | ✅ Handled | Stage 6 — synthesise `token` events by replaying the grounded final `AIMessage` content (word-chunked); pass through real `on_chat_model_stream` chunks when a node does emit them and suppress the replay for that node |
| B013 | An `interrupt()` does NOT surface as an event in the `astream_events` stream — the stream just ends. Reading the pending action requires querying graph state after the loop. | Stage 6 routes_chat.py | ✅ Handled | Stage 6 — after the event loop, `await graph.aget_state(config)` and read `snapshot.interrupts[0].value` (a `tuple[Interrupt, ...]`); emit `confirm_request` and hold (no `done`) when present |
| B014 | httpx `ASGITransport` does NOT run FastAPI lifespan events, so `app.state.graph` was never set under the test client. | Stage 6 conftest.py | ✅ Handled | Stage 6 — the offline test harness bypasses the production lifespan and wires `app.state` (settings/tools/graph/bg_tasks) directly; the production lifespan still runs under uvicorn |

## Assumptions Made
| Assumption | Stage | Risk Level |
|------------|-------|------------|
| ~~Storefront MCP endpoint is available on dev stores at /api/mcp~~ | 0 | ✅ Verified in Stage 1 |
| ~~Shopify MCP uses JSON-RPC 2.0 with protocol version 2025-03-26~~ | 1 | ✅ Verified — storefront-renderer v0.1.0 |
| ~~PRD tool name search_shop_catalog~~ → actual name is `search_catalog` | 1 | ✅ Corrected — all code must use `search_catalog` |
| ~~Prices returned in minor units (paise) — must divide by 100 for display~~ → **units differ per tool**: `search_catalog` sends minor units (39900=₹399), `get_product_details` sends major-unit strings ("399.0"). Stylist normalises both to major-unit strings at card extraction | 1→4 | ✅ Corrected Stage 4 |
| Product IDs use GID format (gid://shopify/Product/...) | 1 | Low — verified |
| search_catalog uses nested params: `{catalog: {query: "..."}}` not flat | 1 | Low — verified |
| UCP response version is 2026-04-08 (may change) | 1 | Medium — monitor |
| langchain-mcp-adapters supports streamable HTTP transport | 0 | ✅ Verified Stage 3 — v0.3.0 accepts `streamable_http` (aliases `http`, `streamable-http`) |
| langchain-mcp-adapters pinned at 0.3.0 (req says >=0.1); `MultiServerMCPClient({...}).get_tools()` is the load API | 3 | Low |
| Loader tries transports `streamable_http`→`http`→`sse`, advancing only on `ValueError` (unknown transport); other errors propagate | 3 | Low |
| Groq raises its OWN SDK exceptions (`groq.RateLimitError`/`groq.APIConnectionError`), not `openai.*` (openai not installed); `groq>=0.11` added to requirements | 3 | Low |
| ~~FakeMCP canned shapes: prices in paise (int)…~~ — Stage 3's search/details shapes were INFERRED and wrong. Re-recorded live in Stage 4: `search_catalog` products use `id` (not `product_id`), `price_range.min/max` are `{amount,currency}` objects (paise int), `availability.available` is nested, images hang off each variant's `media[]`, payload carries an untrusted `instructions` field. `get_product_details` = `{product:{product_id, price_range w/ "399.0" strings, selectedOrFirstAvailableVariant}, instructions}` | 3→4 | ✅ Corrected Stage 4 (cart/policy shapes still Stage 3 — revisit Stage 5) |
| LangGraph 1.2.4 (venv): `MessagesState` import from `langgraph.graph`; async node fns return partial-state dicts; `StateGraph`/`START`/`END`/`add_conditional_edges(node, selector, mapping)` all as specced; `.compile(checkpointer=…)` | 4 | Low — verified |
| Supervisor uses prompt-engineered JSON output (parse + default) rather than `.with_structured_output()` — robust to Groq tool-calling quirks and gives a clean "default to stylist" failure path | 4 | Low |
| Stylist ReAct loop is hand-rolled (not `create_react_agent`) — needed per-turn control over the tool-call CAP, the sanitiser boundary on every result, and product_cards extraction from raw tool JSON | 4 | Low |
| Tool budget counts EXECUTED tool calls (not loop iterations); parallel tool_calls beyond the cap are answered with a "budget exhausted" ToolMessage so the provider contract (every tool_call needs a response) holds | 4 | Low |
| product_cards rides in the final AIMessage's `additional_kwargs` (keeps VastraState as specced); intra-turn tool/scratchpad messages are NOT persisted to state | 4 | Low |
| MCP adapter tools return `content_and_artifact` → `.ainvoke()` yields a content-block LIST, flattened by `_content_to_text` before json parse (Bug B009) | 4 | Medium — live-verified, but adapter behaviour may shift across versions |
| Graph maps unwired-but-legal routes (cart/support/respond) to END via `_route_or_end` so a valid classification can't KeyError before Stage 5 wires those nodes | 4 | Low |
| Live store domain is `pmcidd-iv.myshopify.com` (product URLs/CDN images resolve against it) | 4 | Low |
| `backend` is a regular package (`backend/__init__.py` added) so pytest inserts the project root, not `backend/`, on sys.path | 3 | Low |
| FallbackChatStreaming only fails over to Gemini before the first chunk is emitted; a mid-stream Groq failure propagates (restart would duplicate output) | 3 | Low |
| LangGraph interrupt() works with a checkpointer | 0 | ✅ Verified Stage 5 with MemorySaver (1.0.3); Postgres/Sqlite saver to be wired in Stage 6 |
| LangGraph 1.0.3: `interrupt(value)` raises `GraphInterrupt`; the value surfaces as `result["__interrupt__"][0].value` from `ainvoke`; resume via `graph.ainvoke(Command(resume=x), config={"configurable":{"thread_id":...}})`. The node **re-executes from the top** on resume (the Nth `interrupt()` call returns the Nth resume value) — so the cart node keeps exactly one interrupt and is deterministic before it (temp 0, sole mutation post-approval) | 5 | Low — live-verified |
| pending_action cannot be written to checkpointed state at the moment of interrupt (an interrupting node never returns); it rides in the interrupt PAYLOAD. Stage 6 reads `__interrupt__` to emit `confirm_request` and may persist it then | 5 | Low |
| Cart prices in `get_cart`/`update_cart` JSON are minor units (paise ints) — `unit_price`/`line_price`/`subtotal` normalised to rupee strings via `_to_rupees`. Cart tool shapes are still the Stage 1/3 recordings; `cart_id` relaxed to optional in the fixture (live update_cart creates a cart when absent) | 5 | Medium — cart tool shapes not yet re-recorded from the live store; revisit when the cart flow runs live |
| `extract_preferences` adds a keyword-only `llm=None` test seam (the documented positional signature is preserved); the merge caps style_tags at 12 and is order-preserving | 5 | Low |
| `product_context` entries gained `price` + per-variant `{id,title}` (Stage 4 documented `{id,title,url,variant_ids}`); `variant_ids` kept for back-compat. Internal grounding only — the frontend renders cart from `cart_update`, not `product_context` | 5 | Low |
| Postgres pool: min_size=1, max_size=10 — ample for a single-process demo backend | 2 | Low |
| Pool open timeout 10s, per-connect/checkout timeout 30s — fail fast on a dead DB | 2 | Low |
| Pool connections opened with autocommit=True + dict_row — each query self-commits; no manual transaction mgmt in queries.py | 2 | Low |
| SQLite uses one shared aiosqlite connection (single-process HF Spaces); PRAGMA foreign_keys=ON enables cascade deletes | 2 | Low |
| SQLite stores timestamps as TEXT (CURRENT_TIMESTAMP, UTC) vs Postgres TIMESTAMPTZ — display/ordering only, no app logic depends on tz | 2 | Low |
| SQLite translation is textual (%s→?, now()→CURRENT_TIMESTAMP, TIMESTAMPTZ→TEXT, BIGSERIAL PRIMARY KEY→INTEGER PRIMARY KEY AUTOINCREMENT) — sufficient for the queries we actually issue, not a general translator | 2 | Medium |
| Host Postgres published on 55432 (not 5432) to coexist with native PostgreSQL installs; in-Docker services still use postgres:5432 | 2 | Low |
| Windows local runs need WindowsSelectorEventLoopPolicy for psycopg async (set in conftest; Stage 6 main.py replicates it at import — done) | 2→6 | ✅ Done Stage 6 |
| LangGraph savers: `AsyncPostgresSaver`/`AsyncSqliteSaver` from `langgraph.checkpoint.{postgres,sqlite}.aio`, both via `from_conn_string(...)` returning an async CM; `await checkpointer.setup()` creates the checkpoint tables (idempotent). Nested as `async with ... around the lifespan yield` | 6 | Low — venv-verified (langgraph-checkpoint-{postgres,sqlite} ≥2.0) |
| `astream_events(version="v2")`: node boundaries arrive as `on_chain_end` with `name`==node-name and `data.output`==the node's partial-state dict (supervisor→`{route,turn_count}`; specialists→`{messages:[final AIMessage(additional_kwargs=...)], fallback_used, ...}`). `metadata.langgraph_node` tags model-stream events. Verified against the real compiled graph + fakes | 6 | Low |
| Token streaming is SYNTHESISED from the final message (nodes use `ainvoke`, FakeLLM isn't a Runnable → no `on_chat_model_stream`). Also prevents leaking supervisor route JSON / intermediate ReAct text. Real stream chunks (future streaming model) pass through and suppress the per-node replay | 6 | Medium — revisit if agents move to streamed final replies |
| Interrupt detection is post-stream via `aget_state().interrupts` (a `StateSnapshot.interrupts` tuple), NOT an event in the stream; `/api/confirm` reads the same to validate `action_id` before `Command(resume=...)` | 6 | Low — live-verified with MemorySaver |
| `sse-starlette` `EventSourceResponse` frames events with `\r\n` and may inject `: ping` comment lines — the test `parse_sse()` tolerates both; `ping=3600` keeps pings out of short turns | 6 | Low |
| httpx `ASGITransport` does not run lifespan; offline API tests wire `app.state` directly and use a `MemorySaver` (the AsyncPostgres/Sqlite savers are exercised only via the production lifespan / curl, not offline tests) | 6 | Low |
| Preference Extractor is fire-and-forget (`asyncio.create_task`) tracked in `app.state.bg_tasks`; runs after the streamed reply, `done` does not wait on it. Tests await `bg_tasks` to assert the upsert | 6 | Low |

---
*Updated automatically at the end of every agent session.*
