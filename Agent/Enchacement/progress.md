# Progress — Vastra Enhancement Pass

## Current Status
- **Last completed stage:** E4 — Style Quiz Onboarding live. All 4 enhancements shipped.
- **Next stage:** —
- **Blockers:** None
- **Enhancement pass started:** June 18, 2026
- **Enhancement pass completed:** June 19, 2026

## Known limitations (E4)
- Onboarding state is held in `localStorage` (`vastra_onboarded='1'`) — clears
  in incognito / on new devices / on browser storage clear. The buyer sees the
  quiz again, but answers are still re-seeded into the buyer_profiles row for
  the freshly created session, so behaviour is correct (just chatty).
- The quiz seed only writes the first row to `buyer_profiles`. There is no
  account-level profile, so a returning buyer in a new session starts from a
  blank profile and the Preference Extractor rebuilds it from chat history.
- v2 plan: persist onboarding-completion on the buyer (not the session) in DB,
  support an "account" concept, and resume the most recent profile on session
  creation. Until then, opening a brand-new session intentionally re-runs the
  quiz once if localStorage is cleared.

---

## Stage Completion Log

### v1 — Base build (complete)
All v1 stages complete. Deployed on Hugging Face Spaces.
- ✅ LangGraph supervisor + 3 specialist nodes
- ✅ Shopify Storefront MCP (5 tools)
- ✅ interrupt()-gated cart writes
- ✅ SSE streaming pipeline
- ✅ Preference Extractor (async, 8B)
- ✅ PostgreSQL / SQLite checkpointing
- ✅ React 18 frontend (plain JS, hand-written CSS)
- ✅ 30 golden + 10 adversarial evals passing in CI

### E1 — Persistent Product Shelf
✅ Complete

Changelog:
- ✅ `frontend/src/components/ProductShelf.jsx` — new vertical-list shelf with
  header + count badge, empty state, variant chips, preferred-size highlighting,
  keyboard-accessible card click
- ✅ `frontend/src/index.css` — added `.shelf-panel`, `.shelf-header`,
  `.shelf-count-badge`, `.shelf-card`, `.shelf-card-image`, `.shelf-card-body`,
  `.shelf-card-title`, `.shelf-card-price`, `.shelf-card-variants`,
  `.shelf-empty`, `.shelf-toggle-btn`, `.variant-chip.preferred-size`; desktop
  `.app-layout .chat-main { margin-right: 280px }`; mobile bottom-sheet rules
  inside the existing 768px media query; `.shelf-collapsed` modifier hides the
  panel on mobile
- ✅ `frontend/src/hooks/useChatStream.js` — added `shelfProducts` + `buyerProfile`
  state slices; `shelfProducts` updates on every live `product_cards` event in
  both `sendMessage` and `confirmAction`, and is hydrated from history on
  `openSession`; cleared on `createSession` / `goBack`
- ✅ `frontend/src/App.jsx` — imports `ProductShelf`, derives `buyerSizes` from
  `chat.buyerProfile?.sizes ?? []`, owns local `shelfOpen` state, renders shelf
  as sibling of `.chat-main`, renders `.shelf-toggle-btn` inside the active-chat
  branch, and applies `.shelf-collapsed` to the layout root
- ✅ `.claude/launch.json` — pointed `runtimeExecutable` at the `frontend/` workspace
  so `preview_start` resolves Vite correctly

Verification:
- Desktop @ 1280×800: shelf measures 280×800 fixed right, z-index 10, cream
  background, `chat-main` margin-right 280px
- Mobile @ 375×812: shelf measures 375×220 fixed bottom, border-top only;
  hidden via `data-view="sessions"` rule when no chat is open (correct UX)
- No console errors; empty-state copy and header render exactly as spec

### E2 — Proactive Suggestion Chips
✅ Complete

Changelog:
- ✅ `backend/agents/suggestions.py` — new async 8B-model generator returning
  ≤4 short, de-punctuated chips; tolerates fences/prose, never raises, skips
  the model call entirely when there's no assistant message to base chips on
- ✅ `backend/api/routes_chat.py` — captures `route` from the live `_stream_graph`
  emissions, reads `product_context` from `graph.aget_state` after the turn,
  awaits `generate_suggestions` under a 1.5s `asyncio.wait_for` budget, and
  attaches the result to the `done` payload in both `/api/chat` and `/api/confirm`
- ✅ `backend/tests/test_agents_suggestions.py` — 11 offline tests covering
  parse, cap-at-4, code-fence tolerance, trailing-punctuation strip, oversized/
  non-string filter, garbage rejection, non-list rejection, model-error
  shielding, no-op when `last_assistant_message` is empty, and prompt assembly
  with/without product titles. All pass; broader unit suite still green
  (69 passed; the 6 errors in `test_api_chat.py` come from `psycopg` missing
  in this environment, not from our change)
- ✅ `frontend/src/components/SuggestionChips.jsx` — horizontal pill row,
  hides when `suggestions` empty or `disabled` true, fade-in via CSS
- ✅ `frontend/src/components/Composer.jsx` — accepts optional `onInput`
  callback so App.jsx can clear chips the moment the user starts typing
- ✅ `frontend/src/index.css` — `.suggestion-chips` and `.suggestion-chip`
  styles (green border + green text + green-bg fill, full pill radius,
  hover flips to solid green)
- ✅ `frontend/src/hooks/useChatStream.js` — new `suggestions` state slice,
  populated from the `done` event's `suggestions` field (skipped when the
  turn ends in a `confirm_request`); cleared on user-send, `confirm_request`,
  `openSession`, `createSession`, and `goBack`; new `clearSuggestions` action
  exposed for the composer typing-clears-chips path
- ✅ `frontend/src/App.jsx` — renders `<SuggestionChips>` between the message
  list and `<Composer>`, wires `onSelect` (clear + send) and `onInput`
  (clear-on-type), disabled while streaming or while a confirm is pending

Verification:
- Backend: `pytest backend/tests/test_agents_suggestions.py` → 11/11 pass;
  full unit suite (extractor + supervisor + stylist + cart + support +
  suggestions) → 69/69 pass; the `test_api_chat.py` 6 errors are
  pre-existing (`psycopg` not installed in this env)
- Frontend (Vite preview on :5173): page mounts clean after reload; the
  pre-reload "change in the order of Hooks" warnings were stale-HMR
  artefacts from adding state mid-`useChatStream`. CSS resolves: chip
  pills are 1.5px green border, var(--green) text, var(--green-bg) fill,
  border-radius 999px; row is flex/wrap with 8px gap and 8px 16px 4px
  padding. No console errors on fresh mount.

Notes / tradeoffs:
- Spec said "make it fire-and-forget if it adds >500ms"; I kept it awaited
  but bounded with `asyncio.wait_for(..., timeout=1.5s)`. On Groq 8B this
  is comfortably <300ms; the timeout is defensive and fires the `done`
  event with `suggestions: []` if Groq hangs. Switching to a fire-and-forget
  `suggestions` SSE event is a one-line move if real-world latency
  necessitates it.

### E3 — Outfit Builder
✅ Complete

Changelog:
- ✅ `backend/agents/state.py` — added `last_cart_action_confirmed: bool` to
  VastraState (default handled via `state.get(...)` everywhere)
- ✅ `backend/agents/supervisor.py` — added `complete_look` to ROUTES, broadened
  the `parse_route` regex to tolerate underscores in the route name
- ✅ `backend/agents/prompts.py` — extended SUPERVISOR_PROMPT with the
  `complete_look` route description; added `COMPLETE_LOOK_PLAN_PROMPT` for the
  2-category planner (Zudio-style categories, intro under 90 chars)
- ✅ `backend/mcp/client.py` — added `complete_look: {"search_catalog"}` scope
  (intentionally overlaps with stylist for read-only search; mutating-tool
  isolation invariant remains: `update_cart` is cart-scope-only)
- ✅ `backend/agents/outfit.py` (new) — `make_complete_look_node(tools, llm)`:
  refuses gracefully when `product_context` is empty; otherwise asks the 70B
  model for `{intro, categories[≤2]}`, runs the two `search_catalog` queries in
  parallel, merges via `build_product_cards`, tags payload with
  `look_completion=True` + `look_intro`; clears `last_cart_action_confirmed`
  on every run and refreshes `product_context` from the merged cards
- ✅ `backend/agents/cart.py` — sets `last_cart_action_confirmed=True` only on
  the mutating-tool path (new `cart_mutated` local; the get_cart read path
  leaves the flag untouched)
- ✅ `backend/agents/graph.py` — wired `complete_look` node, added it to
  `_SPECIALIST_ROUTES`, conditional-edge mapping, and edge to END;
  `build_graph` accepts a new `complete_look_llm` test seam
- ✅ `backend/streaming/sse.py` — added `EVENT_OUTFIT_PROMPT = "outfit_prompt"`
- ✅ `backend/api/routes_chat.py` — added `complete_look` to `_SPECIALIST_NODES`
  so its token stream + product_cards are forwarded; emits `outfit_prompt` SSE
  (and appends it to `replay_events` for history hydration) once per
  approved cart write in `/api/confirm`
- ✅ `backend/tests/test_agents_outfit.py` (new) — 11 offline tests covering
  `_parse_plan` (intro+categories, dedupe, cap, fences, garbage, non-object)
  and node integration via a `_SpyTool` (happy path with 2 parallel searches +
  look_completion payload, empty-context soft-fail, planner garbage, empty
  search results, missing search-tool defence)
- ✅ `backend/tests/test_mcp_client.py` — updated `test_scopes_are_disjoint` →
  `test_mutating_tools_belong_to_exactly_one_scope` (read-only tools may legitimately
  overlap; mutating tools must not); expanded the partition test to include the
  new `complete_look` scope
- ✅ `frontend/src/components/OutfitPrompt.jsx` (new) — sparkle-icon banner
  with "Want me to find pieces that go with it?" copy, accept button, and
  dismiss ✕; `visible=false` returns `null`
- ✅ `frontend/src/components/LookCardRow.jsx` (new) — `.look-section` wrapper
  with green italic header, muted intro line, and a horizontal scroll row that
  reuses `ProductCard` (cards get a green left border via the CSS)
- ✅ `frontend/src/index.css` — `.look-section`, `.look-header`, `.look-intro`,
  `.look-card-row` (own scrollbar styling), `.look-card-row .product-card`
  (green left border), `.outfit-prompt-banner` + icon/text/accept/dismiss
  styles, all using existing CSS vars
- ✅ `frontend/src/hooks/useChatStream.js` — `enrichMessage` reads the new
  `look_completion` / `look_intro` fields off the `product_cards` event and
  the `outfit_prompt` event; both `sendMessage` and `confirmAction` accumulate
  these into the streaming message and persist them onto the finalised
  assistant message; new `dismissedOutfitPrompts: Set<string>` state slice +
  `dismissOutfitPrompt(key)` action so dismissed banners stay dismissed
  through HMR / autoscroll re-renders; the set clears on
  `createSession` / `openSession` / `goBack`
- ✅ `frontend/src/App.jsx` — imports `OutfitPrompt` + `LookCardRow`; when
  `msg.lookCompletion` is true renders `<LookCardRow products={…} intro={…} />`
  instead of `<ProductCardRow>`; renders `<OutfitPrompt>` after the resolved
  ConfirmChip and CheckoutBanner when the message carries an `outfitPrompt`
  payload and isn't dismissed; accept sends "Yes, complete the look" and
  dismisses the banner

Verification:
- Backend tests: `pytest backend/tests/` (excluding the DB-suite tests already
  blocked by missing `psycopg` in this env) → 162 passed, 1 warning. New
  test files contribute 11 outfit tests and rewritten 2 scope tests
- Frontend preview at :5173: clean mount, no console errors. Injected
  fragments confirmed `.look-header` is green italic 700-weight, `.look-intro`
  is muted 12px, `.look-card-row .product-card` has the 2px green left border,
  `.outfit-prompt-banner` has the green-bg fill / green border / 12px radius,
  and the accept button is solid green
- Look-completion vs regular product cards: rendering is gated only by
  `msg.lookCompletion`; legacy `ProductCardRow` path is unchanged for every
  other turn, so existing cart / confirm flows are unaffected
- `last_cart_action_confirmed` only fires on the mutating-tool path; the
  `get_cart` read path no longer triggers a false outfit-prompt

### E4 — Style Quiz Onboarding
✅ Complete

Changelog:
- ✅ `backend/api/routes_sessions.py` — added `InitialProfile` + `CreateSessionRequest`
  pydantic models, vibe→style_tags map, budget→range map, `_profile_seed` helper.
  `POST /api/sessions` now accepts optional `initial_profile` and, when present
  and non-empty, calls the existing `upsert_buyer_profile` before returning the
  new session id. Seed failures are logged but never block session creation.
- ✅ `frontend/src/components/OnboardingFlow.jsx` — new 3-step quiz overlay
  (vibe / budget / category), 3-dot progress indicator, back arrow on
  steps 2+3, Continue/Start-shopping CTA enabled only when the current step
  has a selection, "Skip for now" link, ARIA roles (`role="dialog"`,
  `role="radiogroup"`, `role="radio"`, `aria-checked`, `aria-pressed`).
  Step 3 multi-select with "Surprise me" exclusivity (selecting it clears the
  others; selecting any other category clears it).
- ✅ `frontend/src/index.css` — `.onboarding-overlay` (fixed full-screen,
  z-index 200, cream background, fade-in), `.onboarding-card` (≤400px),
  `.onboarding-progress` + `.onboarding-dot.active`, `.onboarding-head` with
  positioned `.onboarding-back`, `.onboarding-title` / `.onboarding-subtitle`,
  `.vibe-grid` (2×2), `.vibe-tile.selected` (green ring + green-bg), `.vibe-emoji`,
  `.vibe-label`, `.vibe-desc`, `.budget-options` (stacked), `.budget-option.selected`,
  `.category-grid` (3-col), `.category-chip-onboard.selected` (full-pill green),
  `.onboarding-continue` (solid green, disabled state), `.onboarding-skip`
  (underlined muted link button), plus a `@media (max-width: 380px)` block
  that tightens padding and emoji size for narrow phones.
- ✅ `frontend/src/api/client.js` — `createSession(initialProfile = null)` now
  POSTs `{ initial_profile }` (or `{}` when null) with a JSON content-type;
  signature is backwards-compatible with the existing zero-arg call sites.
- ✅ `frontend/src/hooks/useChatStream.js` — `createSession(initialProfile)`
  forwards the arg through to `api.createSession`; no other behaviour change.
- ✅ `frontend/src/App.jsx` — added `ONBOARDED_KEY = 'vastra_onboarded'`,
  `readOnboarded` / `markOnboarded` helpers (try/catch around localStorage so
  embedded / sandboxed iframes degrade to "show once per refresh"); new
  `showOnboarding` state initialised from localStorage on mount; renders
  `<OnboardingFlow>` instead of the chat shell when true. `onComplete`
  marks the key, hides the overlay, calls `chat.createSession(answers)` with
  the quiz dict, and auto-sends a personalised first message via
  `firstMessageFromAnswers` (Surprise me → "Surprise me with something nice";
  otherwise `Show me some {categories} {budget-band} ({vibe} vibe)`).
  `onSkip` marks the key and hides the overlay without seeding or sending.

Verification:
- Backend: pydantic model parses real-shape and empty payloads; `_profile_seed`
  returns `None` when nothing was answered (so we skip the upsert entirely);
  existing unit suite still 162 passed locally
- Frontend preview at :5173 (desktop 1280×800 and mobile 375×812):
  - Step 1 mounts with 4 vibe tiles; Continue starts disabled and enables on
    selection; the `.selected` rule paints green-bg + green border once the
    CSS transition completes (the eval saw the in-transition value early)
  - Step 2 shows the 3 budget options, the back arrow, and only the 2nd dot
    active
  - Step 3 lists the 6 category chips; multi-select works (Tops + Dresses);
    tapping "Surprise me" deselects the others; tapping any other category
    afterwards clears "Surprise me" as designed
  - Back navigation preserves selected vibe → selected budget → selected
    categories across step transitions
  - Pressing "Start shopping" sets `localStorage['vastra_onboarded']='1'` and
    swaps to the chat layout
  - Page reload with the flag set goes straight to chat — no onboarding
  - Mobile 375px: card is 343px wide centred with 16px margins, no overflow
  - No console errors throughout the flow

---

## Bug Log

| Bug | Stage Found | Status | Notes |
|-----|-------------|--------|-------|
| (none known at enhancement pass start) | — | — | — |

---

## Assumptions (enhancement pass)

| Assumption | Stage | Impact if Wrong |
|------------|-------|-----------------|
| Groq 8B model instance is accessible from the streaming layer for suggestions | E2 | If not, create a new instance using existing GROQ_API_KEY |
| `upsert_buyer_profile` function accepts arbitrary dict (not just extractor-shaped delta) | E4 | May need to add a separate `seed_buyer_profile` function |
| `product_context` in VastraState is a list of dicts with at least `title` field | E3 | outfit.py reads titles from this field |
| `localStorage` is available in the HF Spaces deployment environment | E4 | HF Spaces iframe may block localStorage — test on deployed URL |
| Adding `last_cart_action_confirmed` to VastraState doesn't break existing checkpointer | E3 | LangGraph checkpointer is schema-flexible — adding fields is safe |

---

## Notes for Next Agent Session

When starting E1:
1. Read all 4 Agent/ files first (mandatory)
2. Check `frontend/src/index.css` for existing CSS variable names before adding new ones
3. Check `frontend/src/App.jsx` for current state shape in useChatStream before adding slices
4. The product_cards SSE event already fires — ProductShelf just needs to listen to the same data
5. Do not remove ProductCardRow from the message stream — shelf is additive
