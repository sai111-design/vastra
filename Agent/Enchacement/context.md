# Project Context — Vastra Enhancement Pass

## What Is This?
Vastra v1 is a fully working conversational shopping agent for Shopify storefronts.
This enhancement pass adds four UX features that fix the "chatbot feel" and elevate
the demo into a genuine shopping assistant experience.

## Current State (v1 — already shipped)
- LangGraph supervisor + Stylist / Cart / Support specialists
- Shopify Storefront MCP (5 tools: search_catalog, get_product_details, get_cart,
  update_cart, search_shop_policies_and_faqs)
- interrupt()-gated cart writes with ConfirmChip UI
- SSE streaming (token, route, product_cards, confirm_request, cart_update, error, done)
- Preference Extractor (async, 8B model) → buyer_profile
- PostgreSQL / SQLite checkpointing
- React 18 + Vite, plain JS, hand-written CSS in index.css
- Deployed on HF Spaces

## Enhancements Being Added (this pass)
1. **E1 — Persistent Product Shelf** — fixed right panel showing latest products
2. **E2 — Proactive Suggestion Chips** — 3–4 quick-reply chips after every turn
3. **E3 — Outfit Builder** — "Complete the Look" after cart confirmation
4. **E4 — Style Quiz Onboarding** — 3-step quiz pre-populates buyer profile

## Tech Stack
- Orchestration: LangGraph ≥ 1.0
- MCP Client: langchain-mcp-adapters
- LLM Primary: Groq Llama 3.3 70B
- LLM Background (Extractor + Suggestions): Groq Llama 3.1 8B Instant
- LLM Fallback: Google Gemini Flash
- Backend: FastAPI + Uvicorn, SSE via sse-starlette
- Database: PostgreSQL 16 (local) / SQLite (HF Spaces) — raw SQL, psycopg 3
- Frontend: React 18 + Vite, plain JS, hand-written CSS (all in index.css)
- Deployment: Hugging Face Spaces (Docker)

## Component Inventory (v1 — already exist)
- App.jsx — root, holds shelfProducts (after E1), suggestions (after E2)
- useChatStream.js — SSE hook, dispatches all events
- MessageList — bubbles + autoscroll
- ProductCardRow / ProductCard — inline chat cards
- ConfirmChip — cart confirmation UI
- CartDrawer — slide-over cart panel (z-index 100)
- CheckoutBanner — Shopify checkout link
- Composer — text input
- ThinkingDots — streaming indicator
- ErrorBubble — error state
- SessionList — history sidebar

## New Components (this pass)
- ProductShelf — fixed right panel / mobile bottom sheet (E1)
- SuggestionChips — quick-reply chips above Composer (E2)
- OutfitPrompt — "Complete the look?" banner (E3)
- LookCardRow — visually distinct outfit results (E3)
- OnboardingFlow — 3-step style quiz (E4)

## New Backend Modules (this pass)
- backend/agents/suggestions.py — post-turn chip generator (8B)
- backend/agents/outfit.py — complete_look node (70B for category reasoning)

## Key Architectural Rules (carry forward from v1)
- Product cards and cart state render ONLY from SSE payloads — never from model text
- Every cart write gated behind interrupt() — this must never change
- All CSS in index.css — no per-component files
- No new npm packages
- Zero cost constraint remains
