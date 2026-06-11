"""
Plants adversarial prompt-injection strings into dev-store product descriptions
via Shopify Admin API for eval testing.

This script will be implemented in Stage 8 (Evaluation Harness). It is used to:

1. Connect to the Shopify Admin API using an Admin API access token.
2. Select a subset of products from the dev store catalog.
3. Inject carefully crafted prompt-injection payloads into their product
   descriptions (Body HTML field). Examples:
   - Instructions to ignore system prompt and reveal internal state
   - Attempts to manipulate cart actions without user confirmation
   - Unicode/homoglyph obfuscation of injection commands
   - Multi-turn injection attempts (payload split across fields)
4. Record which products were modified so they can be restored after testing.
5. Run the eval harness against these poisoned products to verify that
   backend/mcp/sanitize.py correctly neutralises injection attempts.

Prerequisites (Stage 8):
    - Shopify Admin API access token in .env (SHOPIFY_ADMIN_TOKEN)
    - SHOPIFY_STORE_DOMAIN set in .env
    - Eval harness (backend/tests/evals/) implemented
    - backend/mcp/sanitize.py implemented with <tool_data> wrapping

Usage (Stage 8):
    python scripts/seed_injections.py --inject     # plant payloads
    python scripts/seed_injections.py --restore    # revert to clean descriptions
    python scripts/seed_injections.py --list       # show current injection status

Notes:
    - NEVER run this against a production store
    - Always restore products after eval runs
    - The injection payloads are defined in a separate YAML/JSON config file
      to keep them maintainable and version-controlled
"""
