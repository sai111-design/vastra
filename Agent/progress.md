# Progress Tracker — Vastra

## Current Status
- **Last completed stage:** 1
- **Next stage:** Stage 2 — Database & Config
- **Blockers:** None

## Changelog

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

## Assumptions Made
| Assumption | Stage | Risk Level |
|------------|-------|------------|
| ~~Storefront MCP endpoint is available on dev stores at /api/mcp~~ | 0 | ✅ Verified in Stage 1 |
| ~~Shopify MCP uses JSON-RPC 2.0 with protocol version 2025-03-26~~ | 1 | ✅ Verified — storefront-renderer v0.1.0 |
| ~~PRD tool name search_shop_catalog~~ → actual name is `search_catalog` | 1 | ✅ Corrected — all code must use `search_catalog` |
| Prices returned in minor units (paise) — must divide by 100 for display | 1 | Low — verified |
| Product IDs use GID format (gid://shopify/Product/...) | 1 | Low — verified |
| search_catalog uses nested params: `{catalog: {query: "..."}}` not flat | 1 | Low — verified |
| UCP response version is 2026-04-08 (may change) | 1 | Medium — monitor |
| langchain-mcp-adapters supports streamable HTTP transport | 0 | Medium — verified in Stage 3 |
| LangGraph interrupt() works with PostgresSaver checkpointer | 0 | Medium — verified in Stage 5 |

---
*Updated automatically at the end of every agent session.*
