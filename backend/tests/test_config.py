import os
import tempfile

import pytest
from pydantic import ValidationError
from backend.config import Settings, get_settings

def test_settings_load_success(monkeypatch):
    monkeypatch.setenv("SHOPIFY_STORE_DOMAIN", "test.myshopify.com")
    monkeypatch.setenv("DB_BACKEND", "sqlite")

    settings = Settings()
    assert settings.shopify_store_domain == "test.myshopify.com"
    assert settings.db_backend == "sqlite"


def test_settings_db_backend_defaults_to_sqlite(monkeypatch):
    """Sensible default for HF/portfolio deployments — no Postgres needed."""
    # _env_file=None bypasses the on-disk .env so the default isn't shadowed by
    # whatever the developer has in their local file.
    settings = Settings(
        _env_file=None, shopify_store_domain="test.myshopify.com"
    )
    assert settings.db_backend == "sqlite"


def test_settings_sqlite_path_defaults_to_temp_dir():
    """Empty SQLITE_PATH resolves to a platform-appropriate temp file (always writable)."""
    settings = Settings(
        _env_file=None,
        shopify_store_domain="test.myshopify.com",
        db_backend="sqlite",
        sqlite_path="",
    )
    assert settings.sqlite_path == os.path.join(tempfile.gettempdir(), "vastra.db")


def test_settings_explicit_sqlite_path_wins():
    """A non-empty SQLITE_PATH is taken verbatim (e.g. /data on HF Persistent Storage)."""
    settings = Settings(
        _env_file=None,
        shopify_store_domain="test.myshopify.com",
        db_backend="sqlite",
        sqlite_path="/data/vastra.db",
    )
    assert settings.sqlite_path == "/data/vastra.db"


def test_get_settings_prints_friendly_banner_on_missing_var(monkeypatch, capsys):
    """A missing required env var produces a multi-line banner on stderr before raising."""
    from pydantic_settings import SettingsConfigDict

    # Disable .env loading on the Settings class for the duration of this test
    # so the missing-var path is exercised even when the dev has a populated
    # local .env. monkeypatch restores the original config on teardown.
    monkeypatch.setattr(
        Settings,
        "model_config",
        SettingsConfigDict(env_file=None, case_sensitive=False, extra="ignore"),
    )
    monkeypatch.delenv("SHOPIFY_STORE_DOMAIN", raising=False)
    get_settings.cache_clear()

    with pytest.raises(ValidationError):
        get_settings()

    err = capsys.readouterr().err
    assert "CONFIG ERROR" in err
    assert "SHOPIFY_STORE_DOMAIN" in err
    assert "Storefront MCP host" in err
    get_settings.cache_clear()

def test_settings_shopify_store_domain_empty(monkeypatch):
    monkeypatch.setenv("SHOPIFY_STORE_DOMAIN", "   ")
    with pytest.raises(ValidationError) as exc:
        Settings()
    assert "SHOPIFY_STORE_DOMAIN must not be empty" in str(exc.value)

def test_settings_postgres_requires_database_url(monkeypatch):
    monkeypatch.setenv("SHOPIFY_STORE_DOMAIN", "test.myshopify.com")
    monkeypatch.setenv("DB_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "   ")
    
    with pytest.raises(ValidationError) as exc:
        Settings()
    assert "DATABASE_URL is required when DB_BACKEND=postgres" in str(exc.value)

def test_settings_postgres_success_with_database_url(monkeypatch):
    monkeypatch.setenv("SHOPIFY_STORE_DOMAIN", "test.myshopify.com")
    monkeypatch.setenv("DB_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    
    settings = Settings()
    assert settings.db_backend == "postgres"
    assert settings.database_url == "postgresql://user:pass@localhost/db"
