# Project Rules — Vastra Enhancement Pass

## Code Conventions
- Plain JavaScript only — no TypeScript
- React 18 functional components + hooks
- No component libraries, no Tailwind, no CSS-in-JS
- All CSS lives in `frontend/src/index.css` — never create separate .css files per component
- CSS custom properties for ALL colours and spacing (use existing var(--ink), var(--green), etc.)
- BEM-ish class naming: `.block`, `.block-element`, `.block--modifier`
- Python 3.11+, PEP 8, async/await throughout the backend

## Architecture Rules
- New SSE event types must be added to the event dispatcher in `backend/streaming/sse.py`
  AND documented in `Agent/implementations.md`
- New agent nodes must be wired into `backend/graph/graph.py` — never called directly
- State fields added to `VastraState` must have a default value and be documented in
  `Agent/implementations.md`
- All DB writes use parameterised raw SQL via psycopg 3 / aiosqlite — no ORM
- New background async tasks follow the `asyncio.create_task` pattern from preference_extractor.py
- Frontend state lives in `useChatStream` hook or `App.jsx` — no global state library

## Do NOT
- Do not install new npm packages (three deps only: react, react-dom, vite)
- Do not install new Python packages without checking requirements.txt first
- Do not create per-component CSS files
- Do not use dangerouslySetInnerHTML anywhere
- Do not read prices, URLs, or product IDs from free text — only from SSE payloads
- Do not change the LangGraph interrupt/confirm flow
- Do not change existing MCP tool bindings
- Do not modify the eval harness or FakeMCPTools fixture
- Do not add features not listed in this playbook's stage scope

## CSS Variable Reference (existing — do not redefine)
- --ink: primary text (near-black)
- --cream: background (off-white)
- --green: brand accent
- --green-bg: light green background (for chips, banners)
- --green-shadow: green focus ring
- --border: card/input border
- --muted: secondary text
- --disabled: disabled state
- --disabled-text: disabled text
- --body: body text
- --overlay: modal overlay backdrop

## Testing Rules
- New agent nodes need at least one test in `backend/tests/` using FakeMCPTools
- Frontend components are verified manually — no new frontend test files required
- Do not break existing test suite (≥80 passing tests must remain green)
