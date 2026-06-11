# Project Context — Vastra

## What Is This?
Vastra is a conversational shopping agent for Shopify storefronts. A buyer chats in natural language; the agent searches the live catalog, shows product cards, answers policy questions, builds a cart with explicit confirmation, and hands off a Shopify-hosted checkout URL. Built on Shopify's Storefront MCP, orchestrated with LangGraph.

## Who Is It For?
- Primary: Buyers shopping on a value-fashion Shopify store (Zudio-style assortment)
- Secondary: Recruiters/interviewers evaluating agentic commerce fluency

## Tech Stack
- **Orchestration:** LangGraph ≥ 1.0 (supervisor graph, checkpointer, interrupts)
- **MCP Client:** langchain-mcp-adapters (streamable HTTP transport)
- **LLM:** Groq Llama 3.3 70B (primary) → Google Gemini Flash (fallback); Groq Llama 3.1 8B Instant (profile extraction)
- **Backend:** FastAPI + Uvicorn, SSE via sse-starlette
- **Database:** PostgreSQL 16 (local) / SQLite (HF Spaces) — raw SQL via psycopg 3
- **Frontend:** React 18 + Vite, plain JavaScript, hand-written CSS
- **Commerce:** Shopify Partners development store + Storefront MCP
- **Observability:** LangSmith Developer free tier
- **Deployment:** Hugging Face Spaces (Docker SDK), GitHub Actions CI

## Architecture Overview
Supervisor (router–specialist) architecture:
1. Buyer message enters → Supervisor classifies intent via structured output → routes to one specialist
2. Stylist (discovery): search_catalog, get_product_details → product_cards event
3. Cart (transactions): get_cart, update_cart → interrupt → confirm → cart_update event
4. Support (policy): search_shop_policies_and_faqs → text reply
5. Preference Extractor runs asynchronously post-turn on the 8B model → upserts buyer_profile
6. LangGraph checkpointer (PostgresSaver / SqliteSaver) persists threads across turns and restarts

## Data Model (4 application tables + LangGraph checkpoint tables)
- **sessions** — id (PK, UUID, = LangGraph thread_id), store_domain, cart_id, created_at, last_active
- **messages** — id, session_id (FK), role, content, events_json, created_at
- **buyer_profiles** — session_id (PK/FK), sizes_json, budget_min, budget_max, style_tags, last_category, updated_at
- **tool_call_log** — id, session_id (FK), agent, tool_name, args_json, status, confirmed, latency_ms, created_at

## Key Features (Priority Order)
1. Product discovery via natural language + buyer profile (Stylist agent)
2. Cart management with interrupt-gated writes (Cart agent)
3. Policy/FAQ grounded answers (Support agent)
4. Buyer memory / preference extraction (Preference Extractor)
5. SSE streaming with structured UI events
6. Session history and checkpoint durability
7. Trajectory evaluation harness (30+ golden, 10+ adversarial)
8. Docker deployment + HF Spaces

## Third-Party Integrations
- **Shopify Storefront MCP:** 5 tools — catalog search, product details, cart CRUD, policy search
- **Groq API:** Primary LLM inference (70B + 8B models)
- **Google Gemini API:** Fallback LLM
- **LangSmith:** Per-turn tracing (optional, free tier)

## Known Constraints
- No discrete GPU — all inference via cloud API free tiers
- Zero cost end-to-end
- Dev store is non-transactable — checkout demo uses Bogus Gateway test cards
- Storefront MCP is a young platform — schemas may drift; tools loaded dynamically at startup
- Context token budget: ≤ 6,000 tokens per LLM call
- Hard cap: 4 MCP tool calls per turn

## File Structure (Target)
See the full repository tree in the PRD Implementation Specification section.
