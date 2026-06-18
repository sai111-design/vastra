"""Application configuration loaded from the environment via pydantic-settings.

This module is the single source of truth for environment-driven settings.
Import :func:`get_settings` anywhere a configuration value is needed; the result
is cached so the ``.env`` file is parsed only once per process.

The defaults are deliberately tuned for the "fresh deploy" path:
``db_backend`` defaults to ``sqlite`` (the lighter, zero-dependency option) and
``sqlite_path`` defaults to the platform's temp directory (always writable by
the runtime user, ephemeral but works without persistent-storage configuration).
Local Postgres users override ``db_backend`` and ``database_url`` in ``.env``;
HF Spaces with Persistent Storage override ``sqlite_path`` to ``/data/...``.
"""

from __future__ import annotations

import os
import sys
import tempfile
from functools import lru_cache
from typing import Literal

from pydantic import ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_sqlite_path() -> str:
    """Cross-platform default: /tmp/vastra.db on Linux/macOS, %TEMP%\\vastra.db on Windows."""
    return os.path.join(tempfile.gettempdir(), "vastra.db")


class Settings(BaseSettings):
    """Strongly-typed view over the variables defined in ``.env.example``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM providers -----------------------------------------------------
    groq_api_key: str = ""
    google_api_key: str = ""

    # --- Commerce / MCP ----------------------------------------------------
    shopify_store_domain: str

    # --- Database ----------------------------------------------------------
    db_backend: Literal["postgres", "sqlite"] = "sqlite"
    database_url: str = ""
    sqlite_path: str = ""

    # --- Agent runtime knobs ----------------------------------------------
    max_tool_calls_per_turn: int = 4
    context_token_budget: int = 6000

    # --- Observability -----------------------------------------------------
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""

    # --- App ---------------------------------------------------------------
    app_env: str = "dev"
    cors_origin: str = "http://localhost:5173"

    @field_validator("shopify_store_domain")
    @classmethod
    def _store_domain_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("SHOPIFY_STORE_DOMAIN must not be empty")
        return value.strip()

    @field_validator("sqlite_path")
    @classmethod
    def _resolve_sqlite_path(cls, value: str) -> str:
        # Field default is "" so a blank value resolves to a per-platform temp
        # path at construction time. An explicit value (e.g. "/data/vastra.db"
        # on HF Spaces with Persistent Storage) is taken verbatim.
        return value.strip() or _default_sqlite_path()

    @model_validator(mode="after")
    def _database_url_required_for_postgres(self) -> "Settings":
        if self.db_backend == "postgres" and not self.database_url.strip():
            raise ValueError("DATABASE_URL is required when DB_BACKEND=postgres")
        return self


# Friendly, one-line-per-issue messages for the env vars users actually set.
_ENV_HINT: dict[str, str] = {
    "shopify_store_domain": (
        "SHOPIFY_STORE_DOMAIN — the Storefront MCP host, e.g. "
        "'your-store.myshopify.com'. Set in .env, as an HF Space secret, or in CI env."
    ),
    "database_url": (
        "DATABASE_URL — Postgres DSN, e.g. 'postgresql://user:pass@host:5432/db'. "
        "Required when DB_BACKEND=postgres. Set DB_BACKEND=sqlite to skip Postgres entirely."
    ),
}


def _format_validation_error(exc: ValidationError) -> str:
    """Render a pydantic ValidationError as a short, human-readable banner."""

    lines = ["", "=" * 68, "CONFIG ERROR — the app cannot start because:", ""]
    for err in exc.errors():
        field = ".".join(str(x) for x in err.get("loc", ()))
        kind = err.get("type", "")
        msg = err.get("msg", "invalid value")

        if kind == "missing":
            hint = _ENV_HINT.get(field, f"Set {field.upper()} in your environment.")
            lines.append(f"  - Missing required env var: {field.upper()}")
            lines.append(f"      {hint}")
        else:
            # ValueError-based validators (custom messages) and everything else.
            lines.append(f"  - {msg}")
            if field in _ENV_HINT:
                lines.append(f"      {_ENV_HINT[field]}")
    lines.append("")
    lines.append(
        "Fix:  set the variable in .env (local), as a Space secret (HF), "
        "or under env: in CI."
    )
    lines.append("=" * 68)
    return "\n".join(lines)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton.

    On validation failure prints a clear, multi-line banner to stderr naming
    the offending variable(s) with set-instructions, then re-raises so callers
    (uvicorn lifespan, tests) see the original exception. The banner means a
    deployer never has to scroll a 50-line pydantic stack to find which env
    var they forgot.
    """

    try:
        return Settings()
    except ValidationError as exc:
        print(_format_validation_error(exc), file=sys.stderr, flush=True)
        raise
