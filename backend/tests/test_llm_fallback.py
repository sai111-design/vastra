"""Tests for the Groq -> Gemini fallback wrapper.

Both LLM providers are replaced with mocks — no real API calls are made. The
``ChatGroq`` / ``ChatGoogleGenerativeAI`` constructors are patched so the
wrappers can be built without API keys, and ``_backoff_seconds`` is zeroed so the
retry path does not actually sleep.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from groq import APIConnectionError, RateLimitError
from langchain_core.messages import AIMessage, AIMessageChunk

import backend.llm.fallback as fallback_mod
from backend.llm.fallback import (
    FALLBACK_MODEL,
    PRIMARY_MODEL,
    SMALL_MODEL,
    FallbackChat,
    FallbackChatStreaming,
)


# ---------------------------------------------------------------------------
# Error builders
# ---------------------------------------------------------------------------
def _rate_limit_error() -> RateLimitError:
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resp = httpx.Response(429, request=req)
    return RateLimitError("rate limited", response=resp, body=None)


def _connection_error() -> APIConnectionError:
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return APIConnectionError(message="connection failed", request=req)


def _stream(chunks):
    """Build an async-generator factory yielding ``chunks``."""

    async def gen(messages, **kwargs):
        for chunk in chunks:
            yield chunk

    return gen


def _raising_stream(exc):
    """Build an async-generator factory that raises before any yield."""

    async def gen(messages, **kwargs):
        raise exc
        yield  # pragma: no cover - marks this as an async generator

    return gen


# ---------------------------------------------------------------------------
# Fixture: patch both providers
# ---------------------------------------------------------------------------
@pytest.fixture
def providers(monkeypatch):
    primary = MagicMock(name="primary")
    fallback = MagicMock(name="fallback")
    groq_cls = MagicMock(name="ChatGroq", return_value=primary)
    genai_cls = MagicMock(name="ChatGoogleGenerativeAI", return_value=fallback)

    monkeypatch.setattr(fallback_mod, "ChatGroq", groq_cls)
    monkeypatch.setattr(fallback_mod, "ChatGoogleGenerativeAI", genai_cls)
    # Don't actually sleep during the retry backoff.
    monkeypatch.setattr(fallback_mod, "_backoff_seconds", lambda attempt: 0.0)

    return SimpleNamespace(
        primary=primary, fallback=fallback, groq_cls=groq_cls, genai_cls=genai_cls
    )


_MESSAGES = [{"role": "user", "content": "show me black tees"}]


# ---------------------------------------------------------------------------
# Construction / model selection
# ---------------------------------------------------------------------------
def test_default_selects_70b_model(providers):
    FallbackChat()
    providers.groq_cls.assert_called_once()
    assert providers.groq_cls.call_args.kwargs["model"] == PRIMARY_MODEL
    providers.genai_cls.assert_called_once()
    assert providers.genai_cls.call_args.kwargs["model"] == FALLBACK_MODEL


def test_small_flag_selects_8b_model(providers):
    FallbackChat(small=True)
    assert providers.groq_cls.call_args.kwargs["model"] == SMALL_MODEL


def test_fallback_used_defaults_false(providers):
    chat = FallbackChat()
    assert chat.fallback_used is False


# ---------------------------------------------------------------------------
# ainvoke — happy path
# ---------------------------------------------------------------------------
async def test_normal_groq_path_returns_primary_response(providers):
    providers.primary.ainvoke = AsyncMock(return_value=AIMessage(content="from groq"))

    chat = FallbackChat()
    result = await chat.ainvoke(_MESSAGES)

    assert result.content == "from groq"
    assert chat.fallback_used is False
    providers.primary.ainvoke.assert_awaited_once()
    providers.fallback.ainvoke.assert_not_called()


async def test_retry_succeeds_without_fallback(providers):
    providers.primary.ainvoke = AsyncMock(
        side_effect=[_rate_limit_error(), AIMessage(content="recovered")]
    )

    chat = FallbackChat()
    result = await chat.ainvoke(_MESSAGES)

    assert result.content == "recovered"
    assert chat.fallback_used is False
    assert providers.primary.ainvoke.await_count == 2


# ---------------------------------------------------------------------------
# ainvoke — failover
# ---------------------------------------------------------------------------
async def test_rate_limit_triggers_gemini_fallback(providers):
    providers.primary.ainvoke = AsyncMock(side_effect=_rate_limit_error())
    providers.fallback.ainvoke = AsyncMock(return_value=AIMessage(content="from gemini"))

    chat = FallbackChat()
    result = await chat.ainvoke(_MESSAGES)

    assert result.content == "from gemini"
    assert chat.fallback_used is True
    # Primary is retried once before giving up: two attempts total.
    assert providers.primary.ainvoke.await_count == 2
    providers.fallback.ainvoke.assert_awaited_once()


async def test_connection_error_triggers_fallback(providers):
    providers.primary.ainvoke = AsyncMock(side_effect=_connection_error())
    providers.fallback.ainvoke = AsyncMock(return_value=AIMessage(content="from gemini"))

    chat = FallbackChat()
    result = await chat.ainvoke(_MESSAGES)

    assert result.content == "from gemini"
    assert chat.fallback_used is True
    # Connection errors are not retried — straight to fallback.
    providers.primary.ainvoke.assert_awaited_once()


async def test_fallback_used_flag_set_only_on_failover(providers):
    providers.primary.ainvoke = AsyncMock(return_value=AIMessage(content="ok"))
    chat = FallbackChat()
    await chat.ainvoke(_MESSAGES)
    assert chat.fallback_used is False

    providers.primary.ainvoke = AsyncMock(side_effect=_rate_limit_error())
    providers.fallback.ainvoke = AsyncMock(return_value=AIMessage(content="g"))
    await chat.ainvoke(_MESSAGES)
    assert chat.fallback_used is True


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------
async def test_streaming_normal_path(providers):
    providers.primary.astream = _stream(
        [AIMessageChunk(content="hello "), AIMessageChunk(content="world")]
    )

    chat = FallbackChatStreaming()
    chunks = [c.content async for c in chat.astream(_MESSAGES)]

    assert "".join(chunks) == "hello world"
    assert chat.fallback_used is False


async def test_streaming_fallback_on_rate_limit(providers):
    providers.primary.astream = _raising_stream(_rate_limit_error())
    providers.fallback.astream = _stream(
        [AIMessageChunk(content="gemini "), AIMessageChunk(content="stream")]
    )

    chat = FallbackChatStreaming()
    chunks = [c.content async for c in chat.astream(_MESSAGES)]

    assert "".join(chunks) == "gemini stream"
    assert chat.fallback_used is True


async def test_streaming_fallback_on_connection_error(providers):
    providers.primary.astream = _raising_stream(_connection_error())
    providers.fallback.astream = _stream([AIMessageChunk(content="g")])

    chat = FallbackChatStreaming()
    chunks = [c.content async for c in chat.astream(_MESSAGES)]

    assert "".join(chunks) == "g"
    assert chat.fallback_used is True
