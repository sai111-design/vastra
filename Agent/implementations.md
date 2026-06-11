# Implementation Details — Vastra

## Decisions Log

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Orchestration | LangGraph ≥ 1.0 | Native checkpointers, interrupt/resume, MCP tool loading |
| LLM routing | Groq primary → Gemini Flash fallback | Zero cost; fastest free tier |
| Extraction model | Llama 3.1 8B Instant | Right-sized for background profile extraction; preserves 70B quota |
| Database access | psycopg 3, raw SQL | Portfolio convention — no ORM |
| MCP transport | Streamable HTTP via langchain-mcp-adapters | Storefront MCP uses JSON-RPC over HTTP |
| Prompt injection boundary | Tool output wrapped in <tool_data> delimiters | MCP results are untrusted input |
| Cart safety | LangGraph interrupt() + Command(resume=) | Write-gating via platform primitive |
| Frontend | React 18 + Vite, plain JS, hand-written CSS | Portfolio convention — no UI libraries |
| Deployment | HF Spaces Docker SDK, SqliteSaver on /data | Free tier, persistent volume |

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
