"""Anthropic AI provider plugin (chat via the official ``anthropic`` SDK)."""

from __future__ import annotations

import importlib.util
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from projectionai.core.config import AnthropicConfig
from projectionai.core.plugin import make_register
from projectionai.services.ai import (
    ChatRequest,
    ChatResult,
    GenerationRequest,
    GenerationResult,
    Message,
)

_logger = logging.getLogger(__name__)


class AnthropicProvider:
    """AI provider using Anthropic's Messages API."""

    def __init__(self, config: AnthropicConfig, client: Any | None = None) -> None:
        self._config: AnthropicConfig = config
        self._name: str = "anthropic"
        self._client: Any | None = client

    @property
    def name(self) -> str:
        return self._name

    async def initialize(self) -> None:
        if importlib.util.find_spec("anthropic") is None:
            raise RuntimeError(
                "Anthropic provider needs the 'anthropic' package "
                "(pip install 'projectionai[anthropic]')."
            )
        if not self._config.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        _logger.info("Anthropic provider initialized (model: %s)", self._config.model)

    async def shutdown(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            await self._client.close()
        self._client = None

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.AsyncAnthropic(api_key=self._config.api_key)
        return self._client

    async def generate(self, _request: GenerationRequest) -> GenerationResult:
        raise NotImplementedError("Anthropic does not generate media.")

    async def generate_stream(
        self,
        _request: GenerationRequest,
    ) -> AsyncIterator[GenerationResult]:
        raise NotImplementedError("Anthropic does not generate media.")
        # pyright: ignore[reportUnreachable] — unreachable; keeps this an async generator
        yield

    def _request_kwargs(self, request: ChatRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._config.model,
            "max_tokens": request.max_tokens,
            # Sampling parameters are not accepted on current Claude models,
            # so temperature is intentionally not sent.
            "messages": [
                {"role": m.role, "content": m.content}
                for m in request.messages
                if m.role in ("user", "assistant")
            ],
        }
        if request.system_prompt:
            kwargs["system"] = request.system_prompt
        return kwargs

    async def chat(self, request: ChatRequest) -> ChatResult:
        started = time.perf_counter()
        response = await self._get_client().messages.create(
            **self._request_kwargs(request)
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return ChatResult(
            message=Message(role="assistant", content=text),
            provider=self._name,
            model=self._config.model,
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    async def chat_stream(self, request: ChatRequest) -> AsyncIterator[ChatResult]:
        started = time.perf_counter()
        text = ""
        async with self._get_client().messages.stream(
            **self._request_kwargs(request)
        ) as stream:
            async for piece in stream.text_stream:
                text += piece
                yield ChatResult(
                    message=Message(role="assistant", content=text),
                    provider=self._name,
                    model=self._config.model,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )


register = make_register(
    name="anthropic",
    version="0.2.0",
    description="Anthropic AI provider",
    factory=AnthropicProvider,
)
