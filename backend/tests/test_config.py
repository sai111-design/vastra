import pytest
from pydantic import ValidationError
from backend.config import Settings

def test_settings_load_success(monkeypatch):
    monkeypatch.setenv("SHOPIFY_STORE_DOMAIN", "test.myshopify.com")
    monkeypatch.setenv("DB_BACKEND", "sqlite")
    
    settings = Settings()
    assert settings.shopify_store_domain == "test.myshopify.com"
    assert settings.db_backend == "sqlite"

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
