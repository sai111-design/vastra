"""Application configuration loaded from the environment via pydantic-settings.

This module is the single source of truth for environment-driven settings.
Import :func:`get_settings` anywhere a configuration value is needed; the result
is cached so the ``.env`` file is parsed only once per process.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    db_backend: Literal["postgres", "sqlite"] = "postgres"
    database_url: str = ""
    sqlite_path: str = "/data/vastra.db"

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

    @model_validator(mode="after")
    def _database_url_required_for_postgres(self) -> "Settings":
        if self.db_backend == "postgres" and not self.database_url.strip():
            raise ValueError("DATABASE_URL is required when DB_BACKEND=postgres")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton."""

    return Settings()
