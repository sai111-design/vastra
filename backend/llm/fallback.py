"""LLM fallback wrapper — Groq primary with transparent Gemini Flash failover.

Every model call in the application goes through one of these wrappers (never a
bare ``ChatGroq`` / ``ChatGoogleGenerativeAI``). The contract:

* **Primary:** Groq Llama 3.3 70B (or 3.1 8B Instant when ``small=True``).
* **Retry:** a single retry on Groq rate-limit, with a short backoff.
* **Failover:** on rate-limit (after the retry) or a connection error, fall over
  to Gemini 2.0 Flash. The switch is transparent to the caller; the only signal
  is the :attr:`fallback_used` flag, which the ``done`` SSE event surfaces.

Groq ships an OpenAI-style SDK but with its *own* exception classes
(``groq.RateLimitError`` / ``groq.APIConnectionError``), which ``langchain-groq``
raises through unchanged — those are what we catch here.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from groq import APIConnectionError, RateLimitError
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

logger = logging.getLogger(__name__)

PRIMARY_MODEL = "llama-3.3-70b-versatile"
SMALL_MODEL = "llama-3.1-8b-instant"
FALLBACK_MODEL = "gemini-2.0-flash"

# Errors that trigger a transparent failover to the Gemini fallback.
_FAILOVER_ERRORS: tuple[type[Exception], ...] = (RateLimitError, APIConnectionError)


def _backoff_seconds(attempt: int) -> float:
    """Exponential backoff delay (seconds) for a given retry attempt."""

    return float(2**attempt)


class FallbackChat:
    """Groq primary; one retry on rate-limit; transparent Gemini Flash failover."""

    def __init__(self, temperature: float = 0.0, small: bool = False) -> None:
        model = SMALL_MODEL if small else PRIMARY_MODEL
        self.primary = ChatGroq(model=model, temperature=temperature)
        self.fallback = ChatGoogleGenerativeAI(
            model=FALLBACK_MODEL, temperature=temperature
        )
        self._fallback_used = False

    @property
    def fallback_used(self) -> bool:
        """Whether the most recent call fell over to the Gemini fallback."""

        return self._fallback_used

    async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
        """Invoke the model, returning a single response message."""

        try:
            return await self._with_retry(self.primary.ainvoke, messages, **kwargs)
        except _FAILOVER_ERRORS as exc:
            logger.warning("Groq unavailable (%s); failing over to %s", type(exc).__name__, FALLBACK_MODEL)
            self._fallback_used = True
            return await self.fallback.ainvoke(messages, **kwargs)

    async def _with_retry(self, fn: Any, *args: Any, max_retries: int = 1, **kwargs: Any) -> Any:
        """Call ``fn``, retrying once on rate-limit with exponential backoff."""

        for attempt in range(max_retries + 1):
            try:
                return await fn(*args, **kwargs)
            except RateLimitError:
                if attempt == max_retries:
                    raise
                await asyncio.sleep(_backoff_seconds(attempt))


class FallbackChatStreaming(FallbackChat):
    """Streaming counterpart of :class:`FallbackChat` using ``.astream()``.

    Yields response chunks. Failover to Gemini is only possible while nothing has
    been emitted yet — once chunks have reached the caller, restarting on the
    fallback model would duplicate output, so a mid-stream error propagates.
    """

    async def astream(self, messages: Any, **kwargs: Any) -> AsyncIterator[Any]:
        """Stream the response, failing over to Gemini before the first chunk."""

        emitted = False
        try:
            async for chunk in self._astream_with_retry(
                self.primary.astream, messages, **kwargs
            ):
                emitted = True
                yield chunk
            return
        except _FAILOVER_ERRORS as exc:
            if emitted:
                # Partial output already delivered — cannot safely restart.
                raise
            logger.warning(
                "Groq streaming unavailable (%s); failing over to %s",
                type(exc).__name__,
                FALLBACK_MODEL,
            )
            self._fallback_used = True

        async for chunk in self.fallback.astream(messages, **kwargs):
            yield chunk

    async def _astream_with_retry(
        self, fn: Any, messages: Any, *, max_retries: int = 1, **kwargs: Any
    ) -> AsyncIterator[Any]:
        """Stream from ``fn``, retrying once on rate-limit if nothing was emitted."""

        for attempt in range(max_retries + 1):
            emitted = False
            try:
                async for chunk in fn(messages, **kwargs):
                    emitted = True
                    yield chunk
                return
            except RateLimitError:
                # Only safe to retry if the stream failed before any output.
                if emitted or attempt == max_retries:
                    raise
                await asyncio.sleep(_backoff_seconds(attempt))
