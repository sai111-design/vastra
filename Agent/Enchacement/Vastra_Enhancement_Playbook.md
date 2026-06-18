# 🗂️ Agent Prompt Playbook: Vastra — UX Enhancement Pass

> **Context:** Vastra v1 is fully working. This playbook adds four targeted enhancements
> that fix the "chatbot feel" and elevate the demo into a genuine shopping assistant UX.
> Generated: June 18, 2026
> Total stages: 4 (no Stage 0 — Agent/ folder already exists)

---

## How to Use This Playbook

1. **Do NOT run Stage 0** — your `Agent/` folder already exists with `rules.md`,
   `context.md`, `implementations.md`, and `progress.md`.
2. Feed each stage prompt to Claude Code (Antigravity) one at a time, in order.
3. Each stage is independently deployable — test it before moving to the next.
4. Every stage ends with a mandatory `Agent/progress.md` update.

### Enhancement Stage Map

| Stage | Enhancement | Layer | Est. Time |
|-------|-------------|-------|-----------|
| E1 | Persistent Product Shelf | Frontend only | 60–90 min |
| E2 | Proactive Suggestion Chips | Backend (minor) + Frontend | 90–120 min |
| E3 | Outfit Builder / Complete the Look | Backend (new route) + Frontend | 2–3 hr |
| E4 | Style Quiz Onboarding Flow | Backend (profile seed) + Frontend | 2–3 hr |

**Deploy after E1 and E2 for an immediate demo-ready state.**
**E3 and E4 are additive — ship them when ready.**

---

## Stage E1 — Persistent Product Shelf

### Read First
Before writing any code, read:
- `Agent/rules.md` — project constraints (no UI libraries, hand-written CSS, plain JS)
- `Agent/context.md` — architecture overview
- `Agent/implementations.md` — SSE event protocol and component contracts
- `Agent/progress.md` — current build state and known bugs

### What You're Building
Right now, `ProductCardRow` renders inside the chat stream and scrolls away. Buyers lose
sight of products they were looking at the moment the next message arrives. This stage adds
a **persistent product shelf** — a fixed right panel (desktop) / bottom sheet (mobile) that
always shows the most recently surfaced product set and updates live as the conversation
progresses. This single change makes Vastra feel like a shopping tool instead of a chat window.

**Zero backend changes required.** This is a pure frontend enhancement.

### Tasks

#### Task 1 — Create `ProductShelf` component
Create `frontend/src/components/ProductShelf.jsx`:

```
Props:
  products: array — same shape as ProductCardRow receives
             { id, title, url, image_url, price:{amount,currency}, variants:[{id,title,available}] }
  buyerSizes: array of strings — from buyer_profile (pass empty array if unavailable)
  onProductClick: fn(product) — sends "Tell me more about [title]" as a message

Behaviour:
  - Renders a vertical list of product cards (not horizontal scroll — this panel has width)
  - Each card: image (left, 72×72px), title, price, variant chips
  - Variant chips matching buyerSizes get class `variant-chip preferred-size` (highlight ring)
  - Sold-out variants get class `variant-chip sold-out` (strikethrough, grey)
  - Clicking any card calls onProductClick(product)
  - If products is empty: render a placeholder — "Products you explore will appear here"
    with a subtle bag icon. No spinner, no loading state — just empty state copy.
  - Header: "Currently Showing" label + product count badge
```

#### Task 2 — Create `ProductShelf` CSS in `frontend/src/index.css`
Add to the existing CSS (do not create a separate file — all CSS lives in index.css):

```
.shelf-panel
  Position: fixed right panel on desktop (width: 280px, top: 0, right: 0, bottom: 0)
  On mobile (≤768px): fixed bottom sheet, height: 220px, left: 0, right: 0
  Background: var(--cream), border-left: 1.5px solid var(--border) (desktop)
  Border-top on mobile
  z-index: 10 (below CartDrawer at z-index: 100)
  overflow-y: auto

.shelf-header
  Padding: 16px, font-weight: 700, font-size: 13px, color: var(--muted)
  Letter-spacing: 1px, text-transform: uppercase
  Display flex, justify-content: space-between, align-items: center

.shelf-count-badge
  Background: var(--ink), color: #fff, border-radius: 999px
  Font-size: 11px, padding: 2px 8px, font-weight: 600

.shelf-card
  Display: flex, gap: 12px, padding: 12px 16px
  Border-bottom: 1px solid var(--border), cursor: pointer
  Transition: background 0.12s
  :hover → background: var(--green-bg)

.shelf-card-image
  Width: 72px, height: 72px, border-radius: 10px
  Object-fit: cover, flex-shrink: 0, background: var(--border)

.shelf-card-body
  Display: flex, flex-direction: column, gap: 4px, min-width: 0

.shelf-card-title
  Font-size: 13px, font-weight: 600, color: var(--ink)
  White-space: nowrap, overflow: hidden, text-overflow: ellipsis

.shelf-card-price
  Font-size: 15px, font-weight: 700, color: var(--ink)

.shelf-card-variants
  Display: flex, gap: 3px, flex-wrap: wrap

.shelf-empty
  Padding: 32px 16px, text-align: center
  Color: var(--muted), font-size: 13px, line-height: 1.6

.variant-chip.preferred-size
  Border-color: var(--green), color: var(--green), font-weight: 700
```

#### Task 3 — Wire `ProductShelf` into `App.jsx`

In `App.jsx`:
- Import `ProductShelf`
- Add `shelfProducts` state — initialised as `[]`
- In `renderMessage`, when a message has `msg.productCards`, also call
  `setShelfProducts(msg.productCards)` — so the shelf always reflects the latest product set
- Read `buyerSizes` from `chat.buyerProfile?.sizes ?? []` (the preference extractor already
  writes this — just read it)
- Add `onProductClick` handler: calls `chat.sendMessage("Tell me more about " + product.title)`
- Render `<ProductShelf>` as a sibling of `.chat-main` inside `.app-layout`

#### Task 4 — Adjust `.app-layout` CSS for the shelf
On desktop, `.chat-main` must not overlap the shelf panel:
```
.app-layout { display: flex; }
.chat-main  { flex: 1; margin-right: 280px; } /* leave room for shelf */
@media (max-width: 768px) {
  .chat-main { margin-right: 0; margin-bottom: 220px; }
}
```

#### Task 5 — Shelf toggle on mobile
On mobile the bottom sheet takes 220px which is tight. Add a small toggle button in the
chat header (`shelf-toggle-btn`) that collapses/expands the shelf:
```
.shelf-toggle-btn
  Position fixed, bottom: 228px, right: 16px (just above the shelf)
  Background: var(--green), color: #fff, border-radius: 50%
  Width: 36px, height: 36px, font-size: 18px
  Box-shadow: 0 2px 8px rgba(0,0,0,0.15)
  Only visible on mobile (display: none on desktop)
```
Track `shelfOpen` boolean state. When closed on mobile: shelf `display: none`,
`chat-main margin-bottom: 0`.

### Acceptance Criteria
- [ ] Right panel appears on desktop with "Currently Showing" header and empty state on load
- [ ] After agent returns product cards, the shelf updates immediately with the same products
- [ ] Shelf products persist when next chat turn arrives (do not clear on new user message)
- [ ] Preferred size variants are highlighted with a green ring
- [ ] Clicking a shelf card sends "Tell me more about [product]" as a message
- [ ] On mobile: bottom sheet appears, toggle button shows/hides it
- [ ] No horizontal scroll — shelf cards stack vertically
- [ ] Cart drawer (z-index 100) still opens correctly on top of everything

### ⚠️ Boundaries
- No backend changes in this stage
- Do not remove `ProductCardRow` from the chat stream — it stays, the shelf is additive
- Do not touch any agent, SSE, or FastAPI code

---

### 📝 End-of-Stage E1: Update Progress
Before finishing, update `Agent/progress.md`:
1. **Changelog** — list every file created/modified with ✅
2. **Current Status** — "E1 complete — Persistent Product Shelf live"
3. **Next Stage** — E2: Proactive Suggestion Chips
4. Update `Agent/implementations.md` with the new `ProductShelf` component contract
   and the `shelfProducts` state slice added to `App.jsx`

---

## Stage E2 — Proactive Suggestion Chips

### Read First
Before writing any code, read:
- `Agent/rules.md`
- `Agent/context.md`
- `Agent/implementations.md`
- `Agent/progress.md`

### What You're Building
After every assistant turn, show 3–4 tappable quick-reply chips above the Composer. These
are contextually generated — not hardcoded — so they're always relevant to the last turn.
A buyer who just saw black tees gets chips like "Show me in blue", "Under ₹500 only",
"Add the first one". Tapping a chip sends it as a message instantly.

This breaks the "I have to know what to type" paralysis that makes chat feel passive.

**Backend change:** Add a `suggestions` array to the `done` SSE event, generated by a
fast async call to Llama 3.1 8B (same pattern as the Preference Extractor).
**Frontend change:** Render chips above the Composer, clear on any user input.

### Tasks

#### Task 1 — Backend: Suggestion Generator (`backend/agents/suggestions.py`)

Create `backend/agents/suggestions.py`:

```python
"""
Async post-turn suggestion generator.
Calls Llama 3.1 8B to produce 3–4 contextual quick-reply chips.
Runs after the main graph turn completes, same pattern as preference_extractor.py.
"""

SUGGESTION_SYSTEM = """You are a shopping assistant suggestion engine.
Given the last assistant message and buyer context, generate 3–4 short, tappable
quick-reply suggestions the buyer might naturally send next.

Rules:
- Each suggestion: 2–6 words max, natural language, no punctuation at end
- Mix action suggestions (Add to cart, Show more) and refinement suggestions (Under ₹500, In black)
- If the last turn showed products: include at least one "Add [product name]" suggestion
- If the last turn answered a policy question: include "What else can I help with"
- Never duplicate the last user message
- Output ONLY a JSON array of strings. No preamble, no markdown fences.
  Example: ["Show me in blue", "Under ₹500 only", "Add the first one", "Any dresses instead"]
"""

async def generate_suggestions(
    last_assistant_message: str,
    last_route: str,
    product_context: list[dict],
    llm,  # The 8B model instance (same as extractor)
) -> list[str]:
    """
    Returns 3–4 suggestion strings. Returns [] on any failure — never raises.
    """
    try:
        context_snippet = ""
        if product_context:
            names = [p.get("title", "") for p in product_context[:3]]
            context_snippet = f"Products shown: {', '.join(names)}"

        user_content = f"""Last assistant message: {last_assistant_message[:400]}
Route: {last_route}
{context_snippet}

Generate suggestions:"""

        from langchain_core.messages import SystemMessage, HumanMessage
        response = await llm.ainvoke([
            SystemMessage(content=SUGGESTION_SYSTEM),
            HumanMessage(content=user_content),
        ])
        raw = response.content.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        import json
        suggestions = json.loads(raw)
        if not isinstance(suggestions, list):
            return []
        return [str(s) for s in suggestions[:4] if isinstance(s, str) and len(s) < 60]
    except Exception:
        return []
```

#### Task 2 — Backend: Emit `suggestions` in the `done` event

In `backend/streaming/sse.py` (or wherever `_stream_graph` lives and emits the `done` event):

- After the graph turn finishes and before emitting `done`, fire the suggestion generator
  as an `asyncio.create_task` (same pattern as the preference extractor background task)
- **BUT** — suggestions need to arrive before `done` so the frontend can render them
  immediately. So: `await` the suggestion call (it's fast — 8B model, <300ms on Groq)
  rather than fire-and-forget.
- Pass to `generate_suggestions`:
  - `last_assistant_message`: the final assistant text from the last `AIMessage` in state
  - `last_route`: from `state.get("route", "respond")`
  - `product_context`: `state.get("product_context", [])`
  - `llm`: the same 8B model instance used by the preference extractor

- Modify the `done` event payload:
```python
# Before:
yield format_sse("done", {"turn_id": turn_id, "fallback_used": fallback_used})

# After:
suggestions = await generate_suggestions(last_msg, route, product_context, small_llm)
yield format_sse("done", {
    "turn_id": turn_id,
    "fallback_used": fallback_used,
    "suggestions": suggestions,  # [] if generation failed
})
```

#### Task 3 — Frontend: `SuggestionChips` component

Create `frontend/src/components/SuggestionChips.jsx`:

```
Props:
  suggestions: string[] — from the done event
  onSelect: fn(text: string) — called when a chip is tapped
  disabled: bool — true while streaming or pendingConfirm

Behaviour:
  - Renders a horizontal flex row of pill buttons
  - Each chip: the suggestion text, no icon
  - On click: calls onSelect(text), which sends it as a message
  - Disappears when user starts typing (controlled externally via suggestions=[])
  - Does not render if suggestions is empty or disabled is true
  - Animate in: fade + slide up (use the existing `fade-in` CSS animation class)
```

#### Task 4 — Add `SuggestionChips` CSS to `index.css`

```
.suggestion-chips
  Display: flex, gap: 8px, flex-wrap: wrap
  Padding: 8px 16px 4px
  Animation: fade-in 0.2s ease

.suggestion-chip
  Border: 1.5px solid var(--green)
  Color: var(--green)
  Background: var(--green-bg)
  Border-radius: 999px
  Padding: 7px 14px
  Font-size: 13px, font-weight: 500
  Cursor: pointer, white-space: nowrap
  Transition: background 0.12s, color 0.12s
  :hover → background: var(--green), color: #fff
  :disabled → opacity: 0.4, cursor: not-allowed
```

#### Task 5 — Wire into `App.jsx`

In `App.jsx` (or `useChatStream` if that's where SSE events are dispatched):
- Add `suggestions` state — initialised as `[]`
- In the SSE `done` event handler: `setSuggestions(event.suggestions ?? [])`
- Clear suggestions: on any user message send → `setSuggestions([])`
- Clear suggestions: when `pendingConfirm` becomes true → `setSuggestions([])`
- Render `<SuggestionChips>` between `<MessageList>` and `<Composer>` (inside `.chat-main`)
- Pass `onSelect`: calls `chat.sendMessage(text)` and `setSuggestions([])`

### Acceptance Criteria
- [ ] After every assistant turn, 3–4 suggestion chips appear above the Composer
- [ ] Chips are contextually relevant — they reflect the last route and shown products
- [ ] Tapping a chip sends it as a user message and chips disappear
- [ ] Typing in the Composer clears chips
- [ ] Chips do not appear while streaming is in progress
- [ ] Chips do not appear when a `confirm_request` is pending
- [ ] If the backend returns `suggestions: []` (generation failed), nothing renders — no errors
- [ ] The `done` event's existing `turn_id` and `fallback_used` fields are unchanged
- [ ] No regression on existing SSE events or cart flows

### ⚠️ Boundaries
- Do not change any agent node logic — suggestions are post-turn, not part of the graph
- Do not change the LangGraph graph topology
- The 8B model call must use the existing model instance — do not create a new one
- If the suggestions call adds >500ms to a turn, make it fire-and-forget and send a
  follow-up `suggestions` SSE event type instead (log this tradeoff in progress.md)

---

### 📝 End-of-Stage E2: Update Progress
Before finishing, update `Agent/progress.md`:
1. **Changelog** — every file created/modified with ✅
2. **Current Status** — "E2 complete — Suggestion Chips live"
3. **Next Stage** — E3: Outfit Builder
4. Update `Agent/implementations.md`:
   - New `done` event payload shape (add `suggestions` field)
   - New `backend/agents/suggestions.py` module
   - New `SuggestionChips` component contract

---

## Stage E3 — Outfit Builder (Complete the Look)

### Read First
Before writing any code, read:
- `Agent/rules.md`
- `Agent/context.md`
- `Agent/implementations.md`
- `Agent/progress.md`

### What You're Building
When a buyer adds an item to cart (or views a product in detail), the agent proactively
suggests what goes with it — "You picked a black tee. Want me to find jeans and sneakers
that'd work with it?" The buyer can accept with one tap. The UI renders a distinct
"Complete the Look" card group — visually separate from regular search results.

This is the highest-impact demo moment: it's the thing Shopify's own built-in AI
doesn't do well for small stores, and it makes Vastra feel like a stylist, not a search box.

### Tasks

#### Task 1 — Backend: New supervisor route label `complete_look`

In `backend/agents/supervisor.py` (wherever the route `Literal` type and routing prompt live):

Add `complete_look` to the route options:
```python
Route = Literal["stylist", "cart", "support", "respond", "complete_look"]
```

Update the supervisor system prompt to include:
```
- complete_look: buyer has just confirmed adding an item to cart, OR explicitly asks
  "what goes with this" / "suggest an outfit" / "complete my look".
  Use this route when cart_id is set AND the last cart action was confirmed.
```

Add routing logic: after a `confirm_request` is resolved with `approved=True`, on the
NEXT turn where the buyer hasn't asked something specific, the supervisor should lean
toward `complete_look`. You can implement this by passing a flag in state:
```python
# In VastraState TypedDict:
last_cart_action_confirmed: bool  # set to True after any approved update_cart
```
Set it in the cart node after successful `update_cart`. Clear it after `complete_look` runs.

#### Task 2 — Backend: `complete_look` specialist node

Create `backend/agents/outfit.py`:

```python
"""
Outfit Builder node — runs when route == 'complete_look'.
Reads the last confirmed cart item from product_context and searches for complementary pieces.
Issues up to 2 parallel MCP search calls (one per complementary category).
"""

OUTFIT_SYSTEM = """You are a fashion stylist for a value-fashion store.
The buyer just added an item to their cart. Suggest 2 complementary clothing categories
that would complete an outfit with it.

Rules:
- Only suggest categories available in a Zudio-style store (tees, jeans, dresses,
  kurtas, sneakers, sandals, accessories, jackets)
- Keep suggestions practical and within a similar price range
- Output ONLY a JSON object:
  {"intro": "one sentence intro", "categories": ["category1", "category2"]}
- Example: {"intro": "Great pick! Here's what pairs well with it:",
             "categories": ["denim jeans", "white sneakers"]}
"""

async def complete_look_node(state: VastraState, config: RunnableConfig) -> dict:
    """
    1. Reads last confirmed product from product_context
    2. Asks LLM for 2 complementary categories (structured output)
    3. Issues search_shop_catalog for each category (up to 2 tool calls)
    4. Returns combined product_cards event tagged as look_completion=True
    """
    ...
```

The node structure mirrors `stylist_node` but:
- Uses the 70B model for the category recommendation call (needs fashion reasoning)
- Issues exactly 2 `search_shop_catalog` calls (one per category) — counts against the
  `MAX_TOOL_CALLS_PER_TURN` budget (set budget to 3 for this route)
- Merges results into a single `product_cards` payload with a new field:
  `look_completion: true` and `look_intro: "Great pick! Here's what pairs well with it:"`

#### Task 3 — Backend: Wire `complete_look` into the graph

In `backend/graph/graph.py`:
- Add the `complete_look` node: `graph.add_node("complete_look", complete_look_node)`
- Add edge from supervisor to `complete_look`:
  `graph.add_conditional_edges("supervisor", route_dispatcher, {..., "complete_look": "complete_look"})`
- Add edge from `complete_look` to `END`

#### Task 4 — Backend: Proactive trigger after cart confirmation

After `/api/confirm` resolves with `approved=True` and the cart update succeeds:
- Emit a new SSE event AFTER the `cart_update` event:
  `event: outfit_prompt`
  `data: {"message": "Want me to find pieces that go with it?", "action": "complete_look"}`

This is not an agent call — it's a static nudge from the API. The frontend handles it.

#### Task 5 — Frontend: `OutfitPrompt` component

Create `frontend/src/components/OutfitPrompt.jsx`:

```
Props:
  visible: bool
  onAccept: fn() — sends "Yes, complete the look" as a message
  onDismiss: fn()

Renders:
  A slim banner below the ConfirmChip resolved state:
  [✨ icon] "Want me to find pieces that go with it?"  [Complete the Look] [✕]
  On accept: calls onAccept(), which triggers complete_look routing
  On dismiss: hides
```

#### Task 6 — Frontend: `LookCardRow` component

Create `frontend/src/components/LookCardRow.jsx`:

```
Props:
  products: array (same shape as ProductCardRow)
  intro: string — the intro text from look_intro field

Renders:
  A section distinct from regular ProductCardRow:
  - Header: "✨ Complete the Look" label (green, italic)
  - Intro text below the header (small, muted)
  - Horizontal scrolling card row — same ProductCard components, but with
    a subtle green left border on each card to visually distinguish them
  - On mobile: same snap scroll behaviour as ProductCardRow
```

#### Task 7 — Frontend: Wire into `App.jsx` / `useChatStream`

In the SSE event dispatcher:
- `outfit_prompt` event → set `showOutfitPrompt: true`
- In `product_cards` event handler: check if payload has `look_completion: true`
  → render `LookCardRow` instead of `ProductCardRow` for that message
- `OutfitPrompt` component: place immediately after the resolved `ConfirmChip`

Add `LookCardRow` CSS to `index.css`:
```
.look-card-row → same as .product-card-row but with:
  padding: 4px 0 6px
  border-left: 2px solid var(--green) on each .product-card inside it

.look-header
  Font-size: 12px, font-weight: 700, color: var(--green), font-style: italic
  Padding: 8px 0 4px, letter-spacing: 0.5px

.look-intro
  Font-size: 12px, color: var(--muted), padding-bottom: 6px

.outfit-prompt-banner
  Display: flex, align-items: center, gap: 10px
  Background: var(--green-bg), border: 1.5px solid var(--green), border-radius: 12px
  Padding: 10px 14px, margin: 4px 0
  Font-size: 13px, color: var(--ink)

.outfit-prompt-accept
  Background: var(--green), color: #fff, border-radius: 8px
  Padding: 6px 12px, font-size: 13px, font-weight: 600, cursor: pointer, flex-shrink: 0

.outfit-prompt-dismiss
  Color: var(--muted), font-size: 18px, cursor: pointer,
  margin-left: auto, line-height: 1, flex-shrink: 0
```

### Acceptance Criteria
- [ ] Supervisor correctly routes "what goes with this" / "complete my look" to `complete_look`
- [ ] After cart confirm, `outfit_prompt` SSE event fires and banner appears
- [ ] Tapping "Complete the Look" triggers a new agent turn that searches 2 complementary categories
- [ ] Look results render in `LookCardRow` with green visual treatment, distinct from regular cards
- [ ] The look intro text from the LLM appears above the cards
- [ ] Dismissing the outfit prompt hides it without sending a message
- [ ] `complete_look` node respects `MAX_TOOL_CALLS_PER_TURN` (≤3)
- [ ] All existing cart, confirm, and product flows unaffected
- [ ] `complete_look` products also update the persistent shelf (E1)

### ⚠️ Boundaries
- Do not change `interrupt()` logic — cart confirmation flow is untouched
- `complete_look` must not run without a confirmed cart item (check `last_cart_action_confirmed`)
- Do not attempt multi-turn outfit building — one round of look completion only in v1
- Write one test: `test_complete_look_route` in `backend/tests/` using `FakeMCPTools`

---

### 📝 End-of-Stage E3: Update Progress
Before finishing, update `Agent/progress.md`:
1. **Changelog** — every file created/modified with ✅
2. **Current Status** — "E3 complete — Outfit Builder live"
3. **Next Stage** — E4: Style Quiz Onboarding
4. Update `Agent/implementations.md`:
   - New `complete_look` route and node
   - `outfit_prompt` SSE event type
   - `look_completion` field on `product_cards` payload
   - `last_cart_action_confirmed` state field
   - New components: `OutfitPrompt`, `LookCardRow`

---

## Stage E4 — Style Quiz Onboarding Flow

### Read First
Before writing any code, read:
- `Agent/rules.md`
- `Agent/context.md`
- `Agent/implementations.md`
- `Agent/progress.md`

### What You're Building
Right now new sessions start with a blank chat and quick-prompt pills. This stage replaces
that with a **3-step visual onboarding quiz** shown once per new session:

- **Step 1 — Vibe:** "What's your style?" — 4 aesthetic tiles with emoji + label
  (Minimal / Streetwear / Ethnic Fusion / Casual Everyday)
- **Step 2 — Budget:** "What's your budget?" — 3 range chips (Under ₹500 / ₹500–₹1500 / ₹1500+)
- **Step 3 — Today's mission:** "What are you shopping for?" — 6 category chips
  (Tops / Bottoms / Dresses / Footwear / Accessories / Surprise me)

On completion, this pre-populates the buyer profile before the first message. The first
product results feel personalised from turn one. This is the single biggest signal that
Vastra is a shopping assistant, not a chatbot.

### Tasks

#### Task 1 — Backend: Accept initial profile seed on session creation

In `POST /api/sessions` handler:

```python
# Request body — extend the existing Pydantic model:
class CreateSessionRequest(BaseModel):
    initial_profile: dict | None = None
    # existing fields if any

# After creating the session row, if initial_profile is provided:
if body.initial_profile:
    await upsert_buyer_profile(session_id, body.initial_profile)
```

The `upsert_buyer_profile` function already exists (used by the Preference Extractor) — just
call it here with the onboarding data. Map the quiz answers:
```python
vibe_to_style_tags = {
    "minimal": ["minimal", "clean", "neutral"],
    "streetwear": ["streetwear", "oversized", "graphic"],
    "ethnic": ["ethnic", "fusion", "traditional"],
    "casual": ["casual", "everyday", "comfort"],
}
budget_to_range = {
    "under_500": (0, 500),
    "500_1500": (500, 1500),
    "above_1500": (1500, 9999),
}
```

#### Task 2 — Frontend: `OnboardingFlow` component

Create `frontend/src/components/OnboardingFlow.jsx`:

```
Props:
  onComplete: fn(profile: {style_tags, budget_min, budget_max, category}) — called when quiz done
  onSkip: fn() — skip directly to chat

State:
  step: 1 | 2 | 3
  answers: { vibe: null, budget: null, category: null }

Step 1 renders a 2×2 grid of vibe tiles:
  Each tile: large emoji (32px) + label + subtle description (1 line)
  Minimal — "Clean lines, neutral tones"
  Streetwear — "Bold, oversized, graphic"
  Ethnic Fusion — "Indian-inspired, festive"
  Casual Everyday — "Comfort-first, relaxed"
  Selected tile gets border: 2px solid var(--green), background: var(--green-bg)

Step 2 renders 3 horizontal budget range chips (full-width stacked on mobile):
  Under ₹500 / ₹500–₹1500 / ₹1500+
  Selected: same green ring treatment

Step 3 renders a 2×3 grid of category chips:
  Tops / Bottoms / Dresses / Footwear / Accessories / Surprise me
  Multiple selection allowed (tap to toggle)
  "Surprise me" deselects all others and selects itself alone

Progress indicator: 3 dots at top, current step filled green
Back arrow on steps 2 and 3
"Continue" button enabled only when current step has a selection
"Skip" link below Continue (small, muted text)

On Step 3 Continue:
  calls onComplete({ style_tags, budget_min, budget_max, categories })
```

#### Task 3 — `OnboardingFlow` CSS in `index.css`

```
.onboarding-overlay
  Position: fixed, inset: 0, background: var(--cream)
  Display: flex, flex-direction: column, align-items: center, justify-content: center
  Z-index: 200, padding: 24px
  Animation: fade-in 0.3s ease

.onboarding-card
  Width: 100%, max-width: 400px
  Display: flex, flex-direction: column, gap: 24px

.onboarding-progress
  Display: flex, gap: 8px, justify-content: center

.onboarding-dot
  Width: 8px, height: 8px, border-radius: 50%
  Background: var(--border)
  .active → background: var(--green)

.onboarding-title
  Font-size: 22px, font-weight: 700, color: var(--ink), text-align: center

.onboarding-subtitle
  Font-size: 14px, color: var(--muted), text-align: center, margin-top: -16px

.vibe-grid
  Display: grid, grid-template-columns: 1fr 1fr, gap: 12px

.vibe-tile
  Border: 2px solid var(--border), border-radius: 16px
  Padding: 20px 14px, cursor: pointer, text-align: center
  Transition: border-color 0.15s, background 0.15s
  :hover → border-color: var(--green)
  .selected → border-color: var(--green), background: var(--green-bg)

.vibe-emoji { font-size: 32px; margin-bottom: 8px; }
.vibe-label { font-size: 14px, font-weight: 600, color: var(--ink) }
.vibe-desc  { font-size: 11px, color: var(--muted), margin-top: 4px }

.budget-options
  Display: flex, flex-direction: column, gap: 10px

.budget-option
  Border: 2px solid var(--border), border-radius: 12px
  Padding: 14px 20px, cursor: pointer, font-size: 16px, font-weight: 600
  Transition: border-color 0.15s, background 0.15s
  .selected → border-color: var(--green), background: var(--green-bg), color: var(--green)

.category-grid
  Display: grid, grid-template-columns: 1fr 1fr 1fr, gap: 8px

.category-chip-onboard
  Border: 2px solid var(--border), border-radius: 999px
  Padding: 10px 8px, cursor: pointer, text-align: center
  Font-size: 13px, font-weight: 500
  .selected → border-color: var(--green), background: var(--green-bg), color: var(--green)

.onboarding-continue
  Background: var(--green), color: #fff, border-radius: 12px
  Padding: 15px, font-size: 15px, font-weight: 700, width: 100%
  :disabled → background: var(--disabled), cursor: not-allowed

.onboarding-skip
  Text-align: center, font-size: 13px, color: var(--muted)
  Cursor: pointer, text-decoration: underline
  :hover → color: var(--ink)

.onboarding-back
  Width: 32px, height: 32px, border-radius: 50%
  Border: 1.5px solid var(--border), cursor: pointer
  Display: flex, align-items: center, justify-content: center
  Font-size: 18px, color: var(--muted)
  :hover → border-color: var(--ink)
```

#### Task 4 — Wire into `App.jsx`

In `App.jsx`:
- Add `showOnboarding` state: `true` if this is a new session (no messages yet) AND it's
  the first session ever (use `localStorage` key `vastra_onboarded` — set it on first
  `onComplete` call, check it on mount)
- Render `<OnboardingFlow>` on top of everything when `showOnboarding === true`
- `onComplete` handler:
  1. Set `localStorage.setItem("vastra_onboarded", "1")`
  2. Call `await chat.createSession(initialProfile)` — pass the profile to POST /api/sessions
  3. Set `showOnboarding = false` → chat view appears
  4. If the category answer was "surprise_me": auto-send "Surprise me with something nice"
     Otherwise: auto-send "I'm looking for [categories.join(', ')]" — this triggers the
     first product turn immediately with the profile already loaded
- `onSkip` handler: same as above but skip the profile seed (call createSession with no profile)

#### Task 5 — Extend `useChatStream.createSession` to accept `initialProfile`

```javascript
// In useChatStream.js
async function createSession(initialProfile = null) {
  const body = initialProfile ? { initial_profile: initialProfile } : {}
  const res = await fetch('/api/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  // ... rest of existing logic
}
```

### Acceptance Criteria
- [ ] New users (no `vastra_onboarded` localStorage key) see the onboarding flow on first load
- [ ] Returning users (key exists) go directly to chat — no onboarding
- [ ] All 3 steps render correctly with correct selection states
- [ ] Back navigation works between steps
- [ ] "Skip" goes directly to chat without a profile seed
- [ ] On complete, `POST /api/sessions` includes `initial_profile` in the body
- [ ] Backend upserts the buyer profile before the first agent turn
- [ ] After onboarding, the first auto-sent message is dispatched and the agent responds
      with personalised products immediately (using the pre-populated profile)
- [ ] The onboarding flow is responsive on mobile (320px minimum width)
- [ ] No localStorage read/write touches any existing session logic

### ⚠️ Boundaries
- Do not change any agent or LangGraph logic — the profile seed goes through the existing
  `upsert_buyer_profile` path, no new graph nodes
- Onboarding only shows on new sessions — never interrupts an existing conversation
- Do not add the onboarding to the HF Spaces health check / cold-start screen
- Write no new tests for the onboarding flow in this stage (it's pure UI, manual verify is fine)

---

### 📝 End-of-Stage E4: Update Progress
Before finishing, update `Agent/progress.md`:
1. **Changelog** — every file created/modified with ✅
2. **Current Status** — "E4 complete — Style Quiz Onboarding live. All 4 enhancements shipped."
3. **Known limitations to document:**
   - Onboarding uses `localStorage` — clears on incognito / new device
   - v2: persist onboarding state in DB against session, support account-level profiles
4. Update `Agent/implementations.md`:
   - `POST /api/sessions` now accepts `initial_profile`
   - `useChatStream.createSession(initialProfile?)` updated signature
   - `vastra_onboarded` localStorage key
   - New `OnboardingFlow` component contract

---

## Appendix A — Updated SSE Event Protocol

Add these new events to `Agent/implementations.md` after E2 and E3:

| Event | Payload Shape | Introduced In |
|-------|--------------|---------------|
| `done` (updated) | `{ turn_id, fallback_used, suggestions: string[] }` | E2 |
| `outfit_prompt` | `{ message: string, action: "complete_look" }` | E3 |

All existing events (`token`, `route`, `product_cards`, `confirm_request`, `cart_update`, `error`, `done`) are unchanged except `done` gets the `suggestions` field.

---

## Appendix B — New State Fields (VastraState)

Add to `Agent/implementations.md`:

| Field | Type | Default | Set By | Read By |
|-------|------|---------|--------|---------|
| `last_cart_action_confirmed` | `bool` | `False` | `cart` node (after approved write) | `supervisor`, `complete_look` node |

---

## Appendix C — New Files Summary

| File | Stage | Type |
|------|-------|------|
| `frontend/src/components/ProductShelf.jsx` | E1 | New component |
| `frontend/src/components/SuggestionChips.jsx` | E2 | New component |
| `frontend/src/components/OutfitPrompt.jsx` | E3 | New component |
| `frontend/src/components/LookCardRow.jsx` | E3 | New component |
| `frontend/src/components/OnboardingFlow.jsx` | E4 | New component |
| `backend/agents/suggestions.py` | E2 | New module |
| `backend/agents/outfit.py` | E3 | New module |

CSS for all components lives in the existing `frontend/src/index.css`.
No new CSS files. No new backend routes except the `initial_profile` param on `POST /api/sessions`.

---

## Appendix D — What NOT to Touch

These are in-scope for a future pass but explicitly out of scope for this playbook:

- Voice input
- Image-based search ("find something like this photo")
- Order tracking / customer account OAuth (v2 PRD item)
- Multi-store routing
- Any changes to the eval harness or `FakeMCPTools`
- Any changes to the LangGraph interrupt/confirm flow
- Any changes to the existing 5 Storefront MCP tool bindings
