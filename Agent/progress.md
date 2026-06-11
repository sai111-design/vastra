# Progress Tracker — Vastra

## Current Status
- **Last completed stage:** 1
- **Next stage:** Stage 2 — Database & Config
- **Blockers:** MCP endpoint verification requires the developer to have a Shopify Partners dev store set up and SHOPIFY_STORE_DOMAIN configured in .env

## Changelog

### 2026-06-11 — Stage 1: Shopify Dev Store & MCP Spike
- ✅ seed/catalog.csv — 75 variant rows across 26 products (t-shirts, oversized tees, jeans, joggers, dresses, kurtas, sneakers, accessories); valid Shopify product CSV import format
- ✅ seed/policies/returns.md — 7-day return/exchange policy with eligibility, non-returnable items, COD refund process
- ✅ seed/policies/shipping.md — Free shipping ≥₹999, standard (5–7 days) and express (2–3 days, ₹149), COD under ₹5000
- ✅ seed/policies/size-guide.md — Measurement tables for regular/oversized tops, bottoms, dresses, footwear with fit notes
- ✅ scripts/verify_mcp.py — Full JSON-RPC verification spike: initialize, tools/list, test search; colour-coded output, error diagnostics
- ✅ scripts/seed_injections.py — Placeholder for Stage 8 adversarial injection testing
- ⚠️ MCP endpoint not yet verified against live store — requires developer to set SHOPIFY_STORE_DOMAIN in .env and run `python scripts/verify_mcp.py`
- 📋 Notes: Developer must import catalog.csv into Shopify admin and create policy pages before running the verification script

### 2026-06-11 — Stage 0: Agent Scaffolding
- ✅ Created project skeleton with all directories and placeholder files
- ✅ Initialized Agent/ folder with rules, context, implementations, progress
- ✅ docker-compose.yml, requirements.txt, package.json, .env.example, .gitignore
- 📋 Notes: No implementation code yet — all files are docstring placeholders

---

## Bug Log
| ID | Description | Found In | Status | Resolved In |
|----|-------------|----------|--------|-------------|
| — | No bugs yet | — | — | — |

## Assumptions Made
| Assumption | Stage | Risk Level |
|------------|-------|------------|
| Storefront MCP endpoint is available on dev stores at /api/mcp | 0 | High — to be verified when developer runs verify_mcp.py |
| langchain-mcp-adapters supports streamable HTTP transport | 0 | Medium — verified in Stage 3 |
| LangGraph interrupt() works with PostgresSaver checkpointer | 0 | Medium — verified in Stage 5 |
| Shopify MCP uses JSON-RPC 2.0 with protocol version 2025-03-26 | 1 | Medium — encoded in verify_mcp.py, verified on first run |
| Shopify product CSV import format uses the standard column headers (Handle, Title, Body (HTML), Vendor, Type, Tags, Option1 Name, etc.) | 1 | Low — well-documented by Shopify |
| MCP response may use SSE-style content-type or newline-delimited JSON | 1 | Medium — verify_mcp.py handles both formats |

---
*Updated automatically at the end of every agent session.*
