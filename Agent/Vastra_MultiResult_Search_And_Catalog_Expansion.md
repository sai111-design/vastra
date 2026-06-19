# Vastra Add-On: Multi-Result Filtered Search + Catalog Expansion

> Two changes bundled together because they're causally linked: the search behavior fix
> only becomes *visible* in a demo if the catalog has enough depth per category to return
> multiple results. Ship the catalog expansion first, then the search fix.

---

## Part 1 — The Problem (in your words, cleaned up)

> "If I type 'I need jeans under ₹500, size 32,' it should load **all** jeans matching that
> filter at once — not one product. Then, if I want to narrow further, the agent should ask
> what specific thing I want, and only then narrow to one product."

This is a real architecture gap, not a misunderstanding. Two compounding causes:

### Cause 1 — The catalog doesn't have enough jeans to show the problem clearly
Current seed catalog: **Jeans category has only 2 products, 6 variant rows total**
(Slim Fit Black, Relaxed Navy — sizes 30/32/34 each). Even a perfect multi-result search
would only ever return 2 products for "jeans." The fix needs more inventory to actually
demo well.

### Cause 2 — The Stylist agent's prompt and tool usage aren't tuned for "show me everything matching"
`search_shop_catalog` is capable of returning multiple matches — it's a search tool, not a
single-lookup tool. The issue is in how the **Stylist agent reasons about and presents**
results: it tends to narrow to a top pick in its reply rather than surfacing the full
matching set first. This is a prompt + response-shaping problem, not an MCP limitation.

---

## Part 2 — The Fix: Two-Phase Search Behavior

### New interaction model

```
Buyer: "I need jeans under ₹500, size 32"
         ↓
Agent: Calls search_shop_catalog with filters (category=jeans, max_price=500, size=32)
         ↓
Agent: Returns ALL matching products as a full result set (not narrowed)
       "Here are N jeans under ₹500 in size 32:" + product_cards (all of them)
         ↓
Buyer: (browses, or says something narrowing, e.g. "show me the black one" /
        "I want something stretchable" / "the second one")
         ↓
Agent: NOW narrows to the one specific product/variant the buyer pointed at
```

This is a **two-phase pattern**: broad-list-first, then narrow-on-request. It's a more
natural retail interaction — like browsing a filtered shelf before picking one item up.

### Why this also makes a better interview story
This is a deliberate **two-phase retrieval pattern** — broad recall first, precision
narrowing second — which is a real information-retrieval design choice you can defend in
an interview. It's the same shape as faceted e-commerce search (filter → result grid →
product detail), translated into a conversational interface. Worth naming explicitly when
you talk about this enhancement.

---

## Part 3 — Implementation Plan for Claude Code

### Stage F1 — Catalog Expansion (do this first)

#### Read First
- `Agent/rules.md`, `Agent/context.md`, `Agent/implementations.md`, `Agent/progress.md`

#### What You're Building
Three new CSV files, in the same schema as `seed/catalog.csv`, that expand the catalog
enough for multi-result filtered search to actually demo well. Sized to fix the thinnest
categories first (Jeans, Accessories) and round out the rest.

#### Task 1 — Generate `seed/catalog_jeans_expansion.csv`

The current Jeans category has 2 products. This is the category your own example
("jeans under ₹500, size 32") will be tested against most — so it needs the most depth.

Generate **8 new jeans products** (in addition to the existing 2), each with 3–4 size
variants (sizes 28–36), following the exact same CSV schema as `seed/catalog.csv`
(handle, title, description_html, vendor, product_type, tags, option1_name, option1_value,
option2_name, option2_value, price, inventory_qty, image_url).

Required spread — **deliberately include sub-₹500 price points** so the filtered-search
example actually returns results:
| Product | Price Range | Sizes |
|---|---|---|
| Basic Straight Jeans — Light Blue | ₹449–₹499 | 28, 30, 32, 34 |
| Budget Slim Jeans — Grey Wash | ₹399–₹449 | 28, 30, 32, 34, 36 |
| Stretch Skinny Jeans — Black | ₹599–₹649 | 28, 30, 32, 34 |
| Distressed Slim Jeans — Blue | ₹899–₹999 | 30, 32, 34 |
| High-Rise Mom Jeans — Indigo (women's) | ₹799–₹899 | 28, 30, 32 |
| Wide-Leg Jeans — Washed Blue (women's) | ₹949–₹1099 | 28, 30, 32, 34 |
| Bootcut Jeans — Dark Indigo | ₹999–₹1099 | 30, 32, 34 |
| Cropped Straight Jeans — Black (women's) | ₹699–₹799 | 28, 30, 32 |

Follow the exact CSV row pattern already in `seed/catalog.csv` (first row per product has
full description_html, subsequent variant rows leave description_html blank). Use
`https://placehold.co/600x800/{hexcolor}/FFFFFF?text={Product+Name}` for image URLs,
matching the existing convention.

#### Task 2 — Generate `seed/catalog_accessories_footwear_expansion.csv`

Accessories (4 products, 7 variants) and Sneakers (3 products, 11 variants) are the next
thinnest categories. Add **6 new accessories + 4 new footwear products**:

Accessories additions:
- Canvas Sling Bag (₹449–₹549)
- Aviator Sunglasses (₹399, One Size)
- Cotton Baseball Cap (₹299–₹349, 2 colors)
- Leather Wallet — Bifold (₹599)
- Printed Silk Scarf (₹349, women's)
- Webbing Crossbody Bag (₹499–₹599)

Footwear additions:
- Canvas Slip-Ons (₹699–₹799, sizes 7–10)
- Chunky Sandals (₹599–₹699, sizes 6–9, women's)
- Running Sports Shoes (₹1199–₹1399, sizes 7–11)
- Flat Loafers (₹799–₹899, sizes 6–10, women's)

Same CSV schema and image URL convention as Task 1.

#### Task 3 — Generate `seed/catalog_ethnic_expansion.csv`

Round out Kurtas (currently 3 products) with **5 new ethnic-wear products** — this also
gives the Outfit Builder (if E3 was already shipped) more to work with for festive looks:
- Embroidered Straight Kurta — ₹899–₹999
- Printed Palazzo Set (kurta + palazzo) — ₹1299–₹1499
- Ethnic Nehru Jacket (men's) — ₹999–₹1199
- Chikankari Kurta — ₹1099–₹1299
- Indo-Western Asymmetric Kurta — ₹1199–₹1399

Same schema and conventions.

#### Task 4 — Update `Agent/implementations.md` catalog summary table

Replace the existing "Seed Catalog Summary" table with the new totals after all three
CSVs are merged in:

```markdown
## Seed Catalog Summary (post-expansion)

| Category | Products | Variant Rows | Price Range (₹) |
|----------|----------|---------------|-------------------|
| T-Shirts | 5 | 16 | 399–549 |
| Oversized Tees | 3 | 9 | 599–699 |
| Jeans | 10 | ~31 | 399–1099 |
| Joggers | 3 | 8 | 699–799 |
| Dresses | 3 | 9 | 799–1099 |
| Kurtas | 8 | ~25 | 699–1499 |
| Sneakers | 7 | ~24 | 699–1499 |
| Accessories | 10 | ~16 | 299–599 |
| **Total** | **49** | **~138** | **299–1499** |
```
(Adjust exact counts to match what's actually generated.)

#### Task 5 — Document the import step (manual, not agent-executable)

Add a note to `Agent/progress.md` under a new "Manual Steps Required" section:

```markdown
## Manual Steps Required (cannot be automated by the coding agent)

- [ ] Import seed/catalog_jeans_expansion.csv into the Shopify dev store admin
      (Products → Import)
- [ ] Import seed/catalog_accessories_footwear_expansion.csv
- [ ] Import seed/catalog_ethnic_expansion.csv
- [ ] Verify via a raw search_shop_catalog curl call that the new products are
      indexed and searchable (Shopify's catalog index can take a few minutes
      to refresh after import)
```

This step happens in the Shopify Admin UI — Claude Code cannot do this, since it requires
your Shopify Partners login. The CSVs it generates are ready to upload directly.

### Acceptance Criteria (F1)
- [ ] 3 new CSV files exist in `seed/`, matching the exact schema of `seed/catalog.csv`
- [ ] Jeans category has at least 8 new products spanning ₹399–₹1099
- [ ] At least 3 jeans products have a variant under ₹500
- [ ] All new rows follow the same handle/title/variant-row CSV convention
- [ ] `Agent/implementations.md` catalog summary table is updated
- [ ] `Agent/progress.md` has the manual import checklist

### ⚠️ Boundaries
- Do not modify `seed/catalog.csv` itself — these are additive new files
- Do not attempt to call the Shopify Admin API to auto-import — CSV generation only
- Do not invent SKUs/prices wildly outside the existing INR price bands (₹299–₹1499) —
  stay consistent with the Zudio-style value-fashion positioning

---

### Stage F2 — Two-Phase Search Behavior (do this after F1)

#### Read First
- `Agent/rules.md`, `Agent/context.md`, `Agent/implementations.md`, `Agent/progress.md`

#### What You're Building
Change the Stylist agent so that a filtered product request returns the **full matching
result set** first, and only narrows to a single product when the buyer's message clearly
asks for one specific item.

#### Task 1 — Update the Stylist system prompt

In `backend/agents/stylist.py` (or wherever `STYLIST_PROMPT` / `STYLIST_SYSTEM` is defined),
update the prompt with explicit two-phase instructions:

```python
STYLIST_PROMPT = """You are a shopping stylist for a value-fashion store.

SEARCH BEHAVIOR — TWO-PHASE PATTERN:

Phase 1 — Broad result, when the buyer describes a CATEGORY with filters
  (e.g. "jeans under ₹500", "black tees size L", "dresses for a wedding"):
  - Call search_shop_catalog with the full filter set (category, price, size, color, etc.)
  - Present ALL matching products returned by the tool — do not pick a favorite or narrow
    to one item in your reply
  - Your text reply should introduce the set: "Here are N jeans under ₹500 in size 32:"
    or similar — never reply with detail about just one product unless only one matched
  - If more than 8 products match, present the top 8 by relevance and mention there are
    more — do not silently drop results

Phase 2 — Narrow to one product, when the buyer's message clearly points at a SPECIFIC item
  (e.g. "the second one", "the black one", "tell me more about [product name]",
  "I'll take the slim fit"):
  - Use product_context from the previous turn to resolve which item they mean
  - Call get_product_details for that specific product/variant if more detail is needed
  - Now it's appropriate to focus your reply on the single item

Never collapse Phase 1 into Phase 2 unprompted. If the buyer's first message already
filters tightly enough that only one product matches, that's fine — but the model should
never choose to show only one product when several match the stated filters.
"""
```

#### Task 2 — Ensure `search_shop_catalog` calls pass full filter parameters

Check the existing tool-calling logic in the Stylist node — confirm that when the buyer
specifies price ceiling and size, those are both passed as filter arguments to
`search_shop_catalog`, not just used as keywords in a free-text query. If the current
implementation only passes a natural-language string, update it to also pass structured
filters where the MCP tool schema supports them (check the tool's actual parameter schema
via the dynamically-loaded MCP tool definition — do not guess parameter names).

#### Task 3 — Confirm `product_cards` SSE payload carries the full result set

Verify in `backend/streaming/sse.py` (or the relevant emission point) that the
`product_cards` event includes **all** products from the tool result, not a truncated or
first-only subset. If there's any existing `[:1]` or similar slicing logic limiting it to
one product, remove it — cap at 8 per Task 1's "more than 8" rule instead.

#### Task 4 — Frontend: confirm `ProductCardRow` (and `ProductShelf`, if E1 was shipped)
already render arrays correctly

No changes expected here — `ProductCardRow` already maps over a `products` array. This
task is verification only: confirm the array isn't being sliced anywhere in the frontend
either (check `App.jsx` and `useChatStream.js` for any accidental `.slice(0, 1)` or
similar).

#### Task 5 — Update eval suite with a multi-result golden scenario

Add one new golden YAML scenario to the eval harness (in the existing evals directory):

```yaml
name: filtered_search_returns_multiple_results
turns:
  - buyer: "I need jeans under ₹500, size 32"
    expected_route: stylist
    expected_tools:
      - name: search_shop_catalog
        args_contain: { category: jeans, max_price: 500 }
    assertions:
      - type: grounding
      - type: min_products_returned
        value: 2   # must return more than one product when multiple match
  - buyer: "Show me the cheapest one"
    expected_route: stylist
    assertions:
      - type: grounding
      - type: max_products_returned
        value: 1   # now it should narrow to one
```

If the eval harness doesn't currently support a `min_products_returned` /
`max_products_returned` assertion type, add it to the assertion engine (small addition,
follows the same pattern as the existing `grounding` and `max_tool_calls` assertions).

### Acceptance Criteria (F2)
- [ ] "Jeans under ₹500, size 32" returns multiple product cards (assuming F1 shipped
      enough inventory) — not a single narrowed pick
- [ ] The assistant's text reply introduces the result set ("Here are N jeans...") rather
      than describing one product in detail
- [ ] A clear follow-up narrowing message ("the second one", "the cheaper one") correctly
      narrows to a single product using existing anaphora resolution via product_context
- [ ] No regression on existing single-match scenarios (a search that genuinely has only
      one match still works correctly)
- [ ] New eval scenario passes in CI
- [ ] `product_cards` payload caps at 8 products max, with no silent truncation to 1

### ⚠️ Boundaries
- Do not change the `MAX_TOOL_CALLS_PER_TURN` budget — this is a presentation/prompt
  change, not a tool-budget change
- Do not change `interrupt()` / cart confirmation logic — this only touches the Stylist
  route, not Cart
- Do not change the grounding guarantee — product cards still render only from MCP tool
  JSON, never from free text
- Anaphora resolution ("the second one") already exists via `product_context` — reuse it,
  do not rebuild it

---

### 📝 End-of-Stage Update (both F1 and F2)
Before finishing each stage, update `Agent/progress.md`:
1. **Changelog** — every file created/modified with ✅
2. **Current Status** — note F1 or F2 complete
3. Update `Agent/implementations.md` with:
   - New catalog totals (after F1)
   - Updated Stylist prompt behavior description (after F2)
   - New `min_products_returned` / `max_products_returned` eval assertion types (after F2)

---

## Part 4 — Quick Reference

| Item | Detail |
|---|---|
| Root cause #1 | Jeans category had only 2 products / 6 variants — too thin to demo multi-result search |
| Root cause #2 | Stylist prompt narrowed to one product in its reply even when multiple matched |
| Fix for #1 | 3 new seed CSVs (~19 new products across Jeans, Accessories, Footwear, Ethnic) |
| Fix for #2 | Two-phase prompt pattern: broad list first, narrow only on explicit follow-up |
| Manual step | You must import the 3 new CSVs into Shopify Admin yourself — not agent-automatable |
| New eval | One golden scenario asserting multi-result-then-narrow behavior |
| Interview framing | "Two-phase retrieval pattern — broad recall, then precision narrowing — same shape as faceted e-commerce search" |
