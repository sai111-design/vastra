# Project Rules — Vastra

## Code Conventions
- Python: follow ruff defaults (PEP 8 superset); type hints on all function signatures
- JavaScript: plain JS (no TypeScript); functional components with hooks
- Naming: snake_case (Python), camelCase (JS), PascalCase (React components)
- File organisation: feature-based modules under backend/ — agents/, api/, db/, llm/, mcp/, streaming/

## Architecture Rules
- ALL SQL is hand-written and parameterised via psycopg 3 — **NO ORM**
- ALL frontend is React 18 + Vite with plain JS and hand-written CSS — **NO component libraries** (no Tailwind, no MUI, no shadcn, no Streamlit, no Gradio)
- LangGraph is the ONLY orchestration framework — do not introduce CrewAI, AutoGen, or AgentScope
- Every LLM call goes through backend/llm/fallback.py — never import ChatGroq or ChatGoogleGenerativeAI directly in agent modules
- Every MCP tool result passes through backend/mcp/sanitize.py before reaching the model
- System prompts live as versioned constants in backend/agents/prompts.py — never inline in agent code
- Cart writes (update_cart) are ALWAYS gated behind LangGraph interrupt + explicit confirmation — no exceptions
- Product cards and cart state render EXCLUSIVELY from SSE event payloads on the frontend — never from free-text parsing

## Do NOT
- Do NOT use any ORM (SQLAlchemy, Tortoise, Django ORM, Prisma)
- Do NOT add Tailwind, styled-components, CSS Modules, or any CSS framework
- Do NOT use react-router — use conditional rendering in App.jsx for view switching
- Do NOT add any dependency not in requirements.txt or package.json without documenting in implementations.md
- Do NOT expose API keys in frontend code
- Do NOT add features not in the PRD without documenting the deviation in progress.md
- Do NOT call update_cart without a preceding approved interrupt — this is a safety invariant
- Do NOT render any price, image URL, or product link from LLM text — only from structured SSE event payloads

## Dependencies Policy
- Backend: only packages listed in requirements.txt; new additions require a note in implementations.md
- Frontend: react, react-dom, vite ONLY; no additional UI libraries
- CDN imports in index.html are forbidden

## Testing Rules
- pytest + pytest-asyncio for all backend tests
- FakeMCP fixture for offline agent testing (conftest.py) — tests must never hit the live store
- Vitest for frontend smoke tests
- Eval harness (tests/evals/) tests golden conversations and adversarial cases — treat as first-class tests, not optional
- Target: ≥ 80 passing tests across backend + evals + frontend
