# Implementation Details — Vastra Enhancement Pass

## SSE Event Protocol (full — includes enhancement additions)

| Event | Payload Shape | Stage Added |
|-------|--------------|-------------|
| `token` | `{ "text": "..." }` | v1 |
| `route` | `{ "agent": "stylist|cart|support|respond|complete_look" }` ✅ E3 | v1 (complete_look added E3) |
| `product_cards` | `{ "products": [...], "look_completion"?: bool, "look_intro"?: str }` ✅ E3 (look_* optional, present only on complete_look turns) | v1 (look fields added E3) |
| `confirm_request` | `{ "action_id", "summary", "line": { variant_id, quantity, title, price } }` | v1 |
| `cart_update` | `{ "cart_id", "lines": [...], "subtotal", "checkout_url" }` | v1 |
| `outfit_prompt` ✅ E3 | `{ "message": "Want me to find pieces that go with it?", "action": "complete_look" }` — fired by `/api/confirm` once per approved cart write, after the `cart_update` event and before `done`. Persisted into the assistant message's replay events so `openSession` rehydrates the banner. | E3 |
| `error` | `{ "message", "recoverable": bool }` | v1 |
| `done` | `{ "turn_id", "fallback_used", "suggestions": string[] }` ✅ E2 | v1 (suggestions added E2) |

## VastraState Fields (additions for this pass)

| Field | Type | Default | Set By | Read By |
|-------|------|---------|--------|---------|
| `last_cart_action_confirmed` ✅ E3 | `bool` | `False` (read via `state.get(...)`; LangGraph TypedDict permits missing key) | cart node — only on the mutating-tool path via the local `cart_mutated` flag (the get_cart read path leaves it untouched) | complete_look node clears it on every run, so the post-cart lean fires at most once per add |

## API Changes

### POST /api/sessions (updated) ✅ E4
```
Request body (optional — empty object is still accepted for backwards compat):
  {
    "initial_profile": {
      "vibe":       "minimal" | "streetwear" | "ethnic" | "casual" | null,
      "budget":     "under_500" | "500_1500" | "above_1500" | null,
      "categories": string[]    // multi-select; "surprise_me" clears others
                                // client-side, so the list is either
                                // ["surprise_me"] or non-surprise items
    } | null
  }

Server-side mapping (backend/api/routes_sessions.py):
  _VIBE_TO_STYLE_TAGS = {
    "minimal":    ["minimal", "clean", "neutral"],
    "streetwear": ["streetwear", "oversized", "graphic"],
    "ethnic":     ["ethnic", "fusion", "traditional"],
    "casual":     ["casual", "everyday", "comfort"],
  }
  _BUDGET_TO_RANGE = {
    "under_500":   (0,    500),
    "500_1500":    (500,  1500),
    "above_1500":  (1500, 9999),   # 9999 = practical ceiling, still a
                                   # meaningful constraint for the Stylist
  }

Behaviour:
- _profile_seed(quiz) → dict | None. Returns None when every field falls to
  default (so the buyer_profiles table stays untouched and the Preference
  Extractor seeds it naturally as the conversation unfolds — pre-E4 behaviour
  for skip / all-default cases).
- "surprise_me" is filtered out of last_category server-side; the auto-sent
  first message carries the buyer's intent instead.
- When non-None, calls the existing upsert_buyer_profile(session_id, sizes_json,
  budget_min, budget_max, style_tags, last_category) before returning. Seed
  failures (DB error, etc.) are logged and swallowed — session creation
  succeeds either way, so the buyer is never blocked at the welcome screen.
- Response shape unchanged: `{ "session_id": <hex> }`.
```

## Component Contracts (new — this pass)

### ProductShelf ✅ shipped (E1)
```
Path: frontend/src/components/ProductShelf.jsx
Props: { products: Product[], buyerSizes: string[] | { [slot]: string }, onProductClick: fn(product) }
  - buyerSizes accepts either a list (["L","M"]) or the backend's dict shape
    ({ top: "L", bottom: "M" }); both are normalised to an upper-cased Set
    before matching against variant titles.
Placement: sibling of .chat-main inside .app-layout
Z-index: 10 (below CartDrawer overlay/drawer at 100/101)
Desktop: fixed right panel, 280px wide; .app-layout .chat-main has margin-right: 280px
Mobile (≤768px): fixed bottom sheet 220px tall; .app-layout .chat-main has
  margin-bottom: 220px; .app-layout.shelf-collapsed hides the panel and zeroes
  the margin. The sessions list view also hides the shelf
  (.app-layout[data-view="sessions"] .shelf-panel).
Toggle button (.shelf-toggle-btn): rendered inside the active-chat JSX in
  App.jsx, display:none on desktop, display:flex on mobile, z-index: 15.
  When the shelf is collapsed it slides to bottom:16px.
Empty state: bag icon + "Products you explore will appear here" — no spinner.
Card behaviour: clicking (or Enter/Space on focus) calls onProductClick(product).
  Sold-out variants get .sold-out (strikethrough); variants whose title
  matches a buyerSizes entry get .preferred-size (green ring).
```

### useChatStream — E1 additions
```
State slices added:
  shelfProducts: Product[]  // [] initial; set on every product_cards event
                             // (live in sendMessage + confirmAction, and
                             // hydrated from message history in openSession);
                             // cleared on createSession + goBack
  buyerProfile : object|null // [reserved] populated by a future stage;
                             // currently null so App reads sizes as []
Returned alongside the existing fields so App.jsx can pass them straight
to <ProductShelf />.
```

### App.jsx — E1 additions
```
- Local state: shelfOpen (bool, default true) for the mobile toggle
- buyerSizes = chat.buyerProfile?.sizes ?? []
- handleShelfClick(product) → chat.sendMessage(`Tell me more about ${product.title}`)
- layoutClass toggles 'shelf-collapsed' on .app-layout when shelfOpen=false
- <ProductShelf /> rendered as a sibling of <main className="chat-main">
- <button.shelf-toggle-btn> rendered inside the active-chat branch
```

### SuggestionChips ✅ shipped (E2)
```
Path: frontend/src/components/SuggestionChips.jsx
Props: { suggestions: string[], onSelect: fn(text), disabled: bool }
Render: <button role="listitem" class="suggestion-chip"> inside a
  <div role="list" class="suggestion-chips">. No icons.
Placement: between the message-list <div> and <Composer> inside .chat-main,
  rendered only when a session is active (inside the chat.currentSessionId branch).
Returns null when suggestions is empty or disabled is true (no wrapper, no
  vertical space taken).
Animation: CSS fade-in 0.2s on the row container.
Cleared by App/useChatStream on: user sends a message (sendMessage),
  confirm_request event arrives, openSession, createSession, goBack, and any
  Composer onInput keystroke.
Populated from: done SSE event's suggestions field. Skipped when the turn
  ended in a confirm_request (no chips while a cart action is pending).
```

### OutfitPrompt ✅ shipped (E3)
```
Path: frontend/src/components/OutfitPrompt.jsx
Props: { visible: bool, onAccept: fn(), onDismiss: fn() }
Returns null when visible is false (no whitespace).
Renders: <div class="outfit-prompt-banner" role="status"> with a sparkle
  span, the static "Want me to find pieces that go with it?" copy, a solid
  green "Complete the Look" accept button, and a muted ✕ dismiss button.
Placement: rendered by App.jsx inside renderMessage for any assistant message
  whose `outfitPrompt` payload is set (after the resolved ConfirmChip and any
  CheckoutBanner).
Triggered by: the `outfit_prompt` SSE event in either the live stream or the
  enrichMessage history-hydration path.
Accept: App.jsx calls `chat.dismissOutfitPrompt(messageKey)` then
  `chat.sendMessage("Yes, complete the look")`. The supervisor classifies
  that as `complete_look` (its prompt lists the phrase).
Dismiss: App.jsx calls `chat.dismissOutfitPrompt(messageKey)`. The
  per-message key is `op-<msg.id>` (turn_id) for persisted messages and
  `op-i-<idx>` as a temporary fallback for in-flight ones; the dismissed
  set lives in useChatStream so HMR and autoscroll re-renders don't bring
  the banner back. It clears on createSession / openSession / goBack.
```

### LookCardRow ✅ shipped (E3)
```
Path: frontend/src/components/LookCardRow.jsx
Props: { products: Product[], intro: string }
Returns null when products is empty.
Renders: <div class="look-section"> containing
  - <div class="look-header">✨ Complete the Look</div>  (green italic 700)
  - <div class="look-intro">{intro}</div>                (muted 12px, only if intro)
  - <div class="look-card-row"> with the same ProductCard children
    as ProductCardRow — visual distinction comes from the CSS rule
    `.look-card-row .product-card { border-left: 2px solid var(--green); }`
Placement: App.jsx renderMessage swaps in LookCardRow instead of
  ProductCardRow whenever `msg.lookCompletion === true`. All other turns
  keep using ProductCardRow — the swap is purely message-local.
Shelf interaction: ProductShelf already updates from every product_cards
  SSE event (E1), so complete_look results land on the shelf too without
  any extra wiring.
```

### OnboardingFlow ✅ shipped (E4)
```
Path: frontend/src/components/OnboardingFlow.jsx
Props: { onComplete: fn({vibe, budget, categories}), onSkip: fn() }
Shown when: App.jsx mounts with localStorage['vastra_onboarded'] !== '1'
  (App.jsx `showOnboarding` state initialised lazily from localStorage)
Hidden after: onComplete or onSkip is called — both flip showOnboarding=false
  and call markOnboarded() which writes '1' to the key.
Z-index: 200 (above CartDrawer @ 100, above the shelf @ 10)

Steps:
  1) Vibe — 4-tile 2×2 grid (.vibe-grid / .vibe-tile.selected). Tiles:
     {minimal, streetwear, ethnic, casual} with emoji + label + 1-line desc.
  2) Budget — 3 stacked options (.budget-options / .budget-option.selected):
     under_500 / 500_1500 / above_1500.
  3) Today's mission — 3-col grid (.category-grid). Multi-select toggles;
     "Surprise me" deselects the others (and tapping any other category
     while "Surprise me" is selected clears it).

Affordances:
  - 3-dot progress indicator at the top, `.onboarding-dot.active` for the
    current step. ARIA: dialog wrapper, radiogroup/radio on steps 1+2,
    group/aria-pressed on step 3.
  - Back arrow appears on steps 2 and 3 only.
  - Continue CTA disabled until the current step has a selection; on step 3
    its label becomes "Start shopping".
  - "Skip for now" link button below the CTA; bypasses the seed entirely.

Mobile: a @media (max-width: 380px) block tightens overlay padding, card
gap, title size, and tile padding/emoji size.
```

### App.jsx — E4 additions
```
Constants:
  ONBOARDED_KEY = 'vastra_onboarded'

Helpers:
  readOnboarded(): bool  — try/catch around localStorage.getItem
  markOnboarded():       — try/catch around localStorage.setItem
  firstMessageFromAnswers({vibe, budget, categories}): string | null
    - categories=[] → null (no auto-send)
    - "surprise_me" → "Surprise me with something nice"
    - else → `Show me some <cat1, cat2 or cat3> <budget-band> (<vibe> vibe)`
             where vibe word is omitted for "casual" (it's the default tone)

State:
  showOnboarding (bool, lazy-initialised from readOnboarded())

Render:
  When appReady=true and showOnboarding=true, returns ONLY
  <OnboardingFlow onComplete={handleOnboardingComplete} onSkip={handleOnboardingSkip} />
  — the chat layout is not mounted, so no SSE streams or session calls fire
  behind the overlay.

Handlers:
  handleOnboardingComplete(answers):
    1. markOnboarded()                       // set vastra_onboarded=1
    2. setShowOnboarding(false)              // unmount overlay
    3. sid = await chat.createSession(answers)  // POSTs initial_profile
    4. if firstMessageFromAnswers(answers)   // skip when categories empty
         chat.sendMessage(firstMessage, sid)
  handleOnboardingSkip():
    1. markOnboarded()
    2. setShowOnboarding(false)
    (no session, no seed, no auto-message — user picks a quick prompt or types)
```

### useChatStream — E4 additions
```
createSession now accepts an optional initialProfile (default null) and
forwards it to api.createSession. All existing zero-arg call sites
(SessionList "+ New", mobile FAB, etc.) keep working unchanged because the
parameter is fully optional. State management on the returned session id
(setCurrentSessionId, setMessages([]), etc.) is unchanged.
```

### api.client — E4 additions
```
createSession(initialProfile = null) — POSTs JSON body to /api/sessions
with Content-Type: application/json. When initialProfile is null/undefined
the body is an empty object {}; otherwise it's { initial_profile }. Throws
"Failed to create session" on non-2xx.
```

### localStorage keys ✅ E4
```
vastra_onboarded = "1"
  Written by App.markOnboarded() at the end of onComplete and onSkip.
  Read by App.readOnboarded() at mount-time only (no live subscription).
  No backend reads or writes this key — clearing it is fully safe.
```

## New Backend Modules

### backend/agents/suggestions.py ✅ shipped (E2)
```
Path: backend/agents/suggestions.py
Module-level constants: MAX_SUGGESTIONS = 4, MAX_SUGGESTION_CHARS = 60
Public:
  async generate_suggestions(
      last_assistant_message: str,
      last_route: str,
      product_context: list[dict] | None,
      llm: Any | None = None,
  ) -> list[str]
Model: 8B (Llama 3.1 8B Instant) via FallbackChat(temperature=0.0, small=True)
  — same constructor pattern as the Preference Extractor. `llm` is a test seam.
Call point: backend/api/routes_chat.py — `_safe_generate_suggestions` runs it
  under `asyncio.wait_for(timeout=SUGGESTION_TIMEOUT_SECS=1.5)` after the
  graph turn completes and before the `done` event ships. Used by both
  /api/chat and /api/confirm. The helper reads `route` + `product_context`
  off `graph.aget_state(config).values`, falling back to the `route` SSE
  emission captured during the stream.
Returns: [] on any failure — empty input, model exception, parse failure,
  non-list, oversize/non-string items, or wait_for timeout. Never raises.
Output: ≤4 strings, each ≤60 chars, trailing .!?, stripped.
Parsing: tolerates ``` fences and stray prose around the JSON array.
```

### routes_chat.py — E2 additions
```
- Imports generate_suggestions
- New helper: _safe_generate_suggestions(graph, config, final_text, default_route)
  → list[str]; bounded by SUGGESTION_TIMEOUT_SECS (1.5s) and shielded
- _stream_graph emissions: caller now tracks `last_route` from the EVENT_ROUTE
  replay tuple so the helper has a fallback when the snapshot read is racy
- Both /api/chat and /api/confirm:
    suggestions = await _safe_generate_suggestions(graph, config, final_text, last_route)
    yield sse(EVENT_DONE, {"turn_id": ..., "fallback_used": ..., "suggestions": suggestions})
```

### useChatStream — E2 additions
```
State slice added:
  suggestions: string[]  // [] initial
Populated by: done event's `suggestions` array, ONLY when the turn did not
  end in a confirm_request (so the cart-pending flow stays clean).
Cleared by: user-send (sendMessage), confirm_request event handler,
  openSession, createSession, goBack, and the new clearSuggestions action
  (used by the Composer onInput hook).
New action: clearSuggestions() → sets suggestions to []
Returned alongside existing state so App.jsx can pass them to <SuggestionChips />.
```

### App.jsx — E2 additions
```
- handleSuggestionSelect(text) → chat.clearSuggestions(); chat.sendMessage(text)
- handleComposerInput() → chat.clearSuggestions() when suggestions is non-empty
- <SuggestionChips suggestions={chat.suggestions} onSelect={handleSuggestionSelect}
                    disabled={chat.isStreaming || !!chat.pendingConfirm} />
  rendered immediately above <Composer>
- Composer now takes optional onInput; App passes handleComposerInput
```

### backend/agents/outfit.py ✅ shipped (E3)
```
Path: backend/agents/outfit.py
Public:
  MAX_OUTFIT_SEARCHES = 2  # one search per planned category
  make_complete_look_node(tools, llm=None) -> async node
  _parse_plan(text) -> (intro: str, categories: list[str])   # used by tests
Model: 70B (Llama 3.3 70B) via FallbackChat(temperature=0.4). The 8B model
  was tried in dev and lacked the fashion-domain judgement for category
  selection; cost is bounded because the planner phase is text-only.
Tool scope: backend.mcp.client.SCOPES["complete_look"] = {"search_catalog"}.
  Read-only — reuses the search tool from the stylist scope. Mutating-tool
  isolation invariant is unchanged: update_cart only appears in the cart scope.
Flow:
  1. If state["product_context"] is empty → reply softly ("tell me which piece
     you'd like me to pair things with") and clear last_cart_action_confirmed.
     Never calls the model or any tool.
  2. Call FallbackChat(temperature=0.4) once with COMPLETE_LOOK_PLAN_PROMPT
     filled with product_context + buyer_profile. Expect JSON
     {"intro": str, "categories": [c1, c2]}. _parse_plan tolerates ``` fences
     and stray prose; dedupes case-insensitively; caps at 2 categories.
  3. If categories is empty (planner garbage / model error) OR there's no
     search tool in scope → reply with the no-results message; clear the flag.
  4. Issue the (≤2) search_catalog calls in parallel via asyncio.gather. Tool
     errors degrade to a missing result, never raise.
  5. Merge with backend.agents.stylist.build_product_cards. If the merged
     product list is empty → no-results reply. Otherwise tag the payload with
     `look_completion=True` and `look_intro = <planner intro>` (falls back to
     "Here's what I'd pair with it." when intro is empty).
  6. Final AIMessage carries the intro as the bubble text and the tagged
     product_cards in additional_kwargs.
Returns:
  {
    "messages": [AIMessage(...)],
    "product_context": <refreshed from merged cards>,   # only on the
                                                        # happy path
    "last_cart_action_confirmed": False,                # always cleared
    "fallback_used": bool,                              # FallbackChat flag
  }
Safety: every failure path returns a non-empty assistant message and clears
  the post-cart flag, so the supervisor never re-routes to complete_look on
  the next turn without explicit buyer intent.
```

### graph.py — E3 additions
```
- Imports make_complete_look_node
- _SPECIALIST_ROUTES now {"stylist", "cart", "support", "complete_look"}
- build_graph accepts complete_look_llm=None test seam
- New node "complete_look" wired from supervisor via conditional edge and
  edge to END; tools_by_agent.get("complete_look", []) so the loader can be
  partial without breaking compilation
```

### routes_chat.py — E3 additions
```
- _SPECIALIST_NODES now includes "complete_look" so the streaming layer
  forwards its token chunks and picks up its product_cards payload
- New constant OUTFIT_PROMPT_PAYLOAD = {"message": "Want me to find pieces
  that go with it?", "action": "complete_look"}
- /api/confirm tracks `cart_updated` from the EVENT_CART_UPDATE replay
  emission; when body.approved AND cart_updated, yields one
  sse(EVENT_OUTFIT_PROMPT, OUTFIT_PROMPT_PAYLOAD) and appends it to
  replay_events so the prompt rehydrates from history alongside the
  assistant message
```

### supervisor.py / prompts.py — E3 additions
```
- ROUTES now {"stylist", "cart", "support", "respond", "complete_look"}
- parse_route's regex broadened from \w to [\w_] so "complete_look" survives
  the prose-fallback scan
- SUPERVISOR_PROMPT extended with the complete_look description ("buyer wants
  pieces that pair with what they just looked at or added to their cart") and
  example phrases that should trigger it ("complete the look", "what goes
  with this", "yes, complete the look")
- New COMPLETE_LOOK_PLAN_PROMPT — Zudio-style category whitelist, two-cat
  cap, intro under 90 chars, JSON-only output
```

### useChatStream — E3 additions
```
State slices added:
  dismissedOutfitPrompts: Set<string>   // per-message keys ("op-<msg.id>")
                                        // banner won't re-show through HMR /
                                        // autoscroll re-renders
Message shape (enrichMessage + live streams):
  productCards: Product[]
  lookCompletion: bool                  // from product_cards.look_completion
  lookIntro: string                     // from product_cards.look_intro
  outfitPrompt: { message, action } | null   // from outfit_prompt SSE event
Live SSE handlers in BOTH sendMessage and confirmAction now case:
  - 'product_cards' → also pulls look_completion + look_intro
  - 'outfit_prompt' → sets acc.outfit (confirmAction only; not emitted on
                       the /api/chat path)
Persisted message (finalised on 'done' and in the disconnect-fallback branch)
carries lookCompletion / lookIntro / outfitPrompt alongside the existing
fields, so re-renders are stable.
New action: dismissOutfitPrompt(messageKey: string) → adds the key to the
dismissed set. Cleared on createSession / openSession / goBack.
```

### App.jsx — E3 additions
```
- Imports OutfitPrompt + LookCardRow
- renderMessage swaps in <LookCardRow products intro> when msg.lookCompletion
  is true; otherwise the existing <ProductCardRow> path runs unchanged
- After the ConfirmChip / CheckoutBanner items, when msg.outfitPrompt is set
  and !chat.dismissedOutfitPrompts.has(promptKey), renders <OutfitPrompt
  visible={true} onAccept={...} onDismiss={...} />
- promptKey = `op-${msg.id}` for persisted turns, `op-i-${idx}` for the
  brief in-flight window before turn_id is known
- onAccept: chat.dismissOutfitPrompt(promptKey); chat.sendMessage("Yes,
  complete the look")
- onDismiss: chat.dismissOutfitPrompt(promptKey) (no message sent)
```

## Supervisor Route Labels (updated)
`Literal["stylist", "cart", "support", "respond", "complete_look"]`

## useChatStream changes
- `createSession(initialProfile = null)` — accepts optional profile, POSTs it in body
- `suggestions` state slice: `[]`, set from done event, cleared on send/confirm
- `shelfProducts` state slice: `[]`, set on every product_cards event
- `showOutfitPrompt` state slice: `bool`, set from outfit_prompt event

## Decisions Log

| Decision | Rationale |
|----------|-----------|
| Suggestions awaited (not fire-and-forget) | Must arrive in done event payload; 8B model is fast enough (<300ms on Groq free tier) |
| Onboarding uses localStorage | Zero backend cost; acceptable for a portfolio demo; v2 will persist in DB |
| All new CSS in index.css | Existing project rule — no per-component CSS files |
| Outfit builder uses 70B for category reasoning | Category suggestion requires fashion domain reasoning; 8B was insufficient in testing |
| outfit_prompt fires from API layer, not graph | It's a static nudge, not an agent decision; keeps graph topology clean |
| LookCardRow is a new component (not a ProductCardRow variant) | Visual distinction is meaningful UX signal; avoids prop-drilling look_completion into ProductCard |
