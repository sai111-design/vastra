# Progress Tracker — Vastra

## Current Status
- **Last completed stage:** 2
- **Next stage:** Stage 3 — MCP Client & Agents
- **Blockers:** None

## Changelog

### 2026-06-11 — Stage 2: Database Foundation & Config
- ✅ backend/config.py — Settings(BaseSettings) over all .env vars; DB_BACKEND literal; cached get_settings() singleton; validators (SHOPIFY_STORE_DOMAIN non-empty, DATABASE_URL required for postgres)
- ✅ backend/db/schema.sql — 4 tables (sessions, messages, buyer_profiles, tool_call_log) + 2 indexes, verbatim from PRD
- ✅ backend/db/connection.py — psycopg AsyncConnectionPool (postgres) + aiosqlite (sqlite) behind get_conn(); init_db() with SQLite DDL translation; graceful connection errors; close_db()
- ✅ backend/db/queries.py — all 10 query functions, fully parameterised (zero string interpolation), results as dicts
- ✅ backend/tests/test_db_queries.py — 8 tests, all passing (7 Postgres + 1 full SQLite-translation round-trip)
- ✅ init_db() verified idempotent (ran twice, no errors); all 4 tables confirmed with correct columns/types
- ✅ requirements.txt — added psycopg-pool, aiosqlite (directly imported; documented in implementations.md)
- ⚠️ Host Postgres port moved 5432 → 55432 (docker-compose.yml, .env, .env.example) to avoid two native PostgreSQL services (v13 on 5432, v18 on 5433) on the dev machine
- ⚠️ docker-compose.yml frontend service given `image: node:20-alpine` so the compose file validates (was missing image/build context, blocking `docker compose up postgres`)
- ⚠️ now() translated to CURRENT_TIMESTAMP for SQLite (a bare function call is invalid in a SQLite DEFAULT clause)

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
| B004 | psycopg async fails on Windows ProactorEventLoop ("cannot use the 'ProactorEventLoop'") | Stage 2 connection.py | ✅ Fixed | Stage 2 — force WindowsSelectorEventLoopPolicy in tests/conftest.py (Stage 6 main.py must do the same for local Windows runs; non-issue in Linux Docker) |
| B005 | Auth "password authentication failed for user vastra" — native PostgreSQL (v13/v18) shadowing host ports 5432/5433 | Stage 2 | ✅ Fixed | Stage 2 — published container on host port 55432 |
| B006 | SQLite "near \"(\": syntax error" — bare datetime('now') invalid in a DEFAULT clause | Stage 2 connection.py | ✅ Fixed | Stage 2 — translate now() → CURRENT_TIMESTAMP for SQLite |
| B007 | `docker compose up postgres` failed: frontend service had no image/build context | Stage 2 docker-compose.yml | ✅ Fixed | Stage 2 — added image: node:20-alpine to frontend service |

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
| Postgres pool: min_size=1, max_size=10 — ample for a single-process demo backend | 2 | Low |
| Pool open timeout 10s, per-connect/checkout timeout 30s — fail fast on a dead DB | 2 | Low |
| Pool connections opened with autocommit=True + dict_row — each query self-commits; no manual transaction mgmt in queries.py | 2 | Low |
| SQLite uses one shared aiosqlite connection (single-process HF Spaces); PRAGMA foreign_keys=ON enables cascade deletes | 2 | Low |
| SQLite stores timestamps as TEXT (CURRENT_TIMESTAMP, UTC) vs Postgres TIMESTAMPTZ — display/ordering only, no app logic depends on tz | 2 | Low |
| SQLite translation is textual (%s→?, now()→CURRENT_TIMESTAMP, TIMESTAMPTZ→TEXT, BIGSERIAL PRIMARY KEY→INTEGER PRIMARY KEY AUTOINCREMENT) — sufficient for the queries we actually issue, not a general translator | 2 | Medium |
| Host Postgres published on 55432 (not 5432) to coexist with native PostgreSQL installs; in-Docker services still use postgres:5432 | 2 | Low |
| Windows local runs need WindowsSelectorEventLoopPolicy for psycopg async (set in conftest; Stage 6 main.py must replicate) | 2 | Medium |

---
*Updated automatically at the end of every agent session.*
