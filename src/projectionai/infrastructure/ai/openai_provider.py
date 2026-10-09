"""OpenAI AI provider plugin (chat via the official ``openai`` SDK)."""

from __future__ import annotations

import importlib.util
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from projectionai.core.config import OpenAIConfig
from projectionai.core.plugin import make_register
from projectionai.services.ai import (
    ChatRequest,
    ChatResult,
    ContentBlockedError,
    GenerationRequest,
    GenerationResult,
    Message,
)

_logger = logging.getLogger(__name__)


class OpenAIProvider:
    """AI provider using OpenAI's Chat Completions API."""

    def __init__(self, config: OpenAIConfig, client: Any | None = None) -> None:
        self._config: OpenAIConfig = config
        self._name: str = "openai"
        self._client: Any | None = client

    @property
    def name(self) -> str:
        return self._name

    async def initialize(self) -> None:
        if importlib.util.find_spec("openai") is None:
            raise RuntimeError(
                "OpenAI provider needs the 'openai' package "
                "(pip install 'projectionai[openai]')."
            )
        if not self._config.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set.")
        _logger.info("OpenAI provider initialized (model: %s)", self._config.model)

    async def shutdown(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            await self._client.close()
        self._client = None

    def _get_client(self) -> Any:
        if self._client is None:
            import openai

            self._client = openai.AsyncOpenAI(
                api_key=self._config.api_key,
                organization=self._config.org_id or None,
            )
        return self._client

    async def generate(self, _request: GenerationRequest) -> GenerationResult:
        raise NotImplementedError("OpenAI image generation is not implemented yet.")

    async def generate_stream(
        self,
        _request: GenerationRequest,
    ) -> AsyncIterator[GenerationResult]:
        raise NotImplementedError("OpenAI image generation is not implemented yet.")
        # pyright: ignore[reportUnreachable] — unreachable; keeps this an async generator
        yield

    def _request_kwargs(self, request: ChatRequest) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.extend(
            {"role": m.role, "content": m.content}
            for m in request.messages
            if m.role in ("user", "assistant")
        )
        # Temperature is omitted: GPT-5 family models accept only the default.
        return {
            "model": self._config.model,
            "messages": messages,
            "max_completion_tokens": request.max_tokens,
        }

    async def chat(self, request: ChatRequest) -> ChatResult:
        started = time.perf_counter()
        response = await self._get_client().chat.completions.create(
            **self._request_kwargs(request)
        )
        if response.choices[0].finish_reason == "content_filter":
            raise ContentBlockedError(self._name)
        text = response.choices[0].message.content or ""
        return ChatResult(
            message=Message(role="assistant", content=text),
            provider=self._name,
            model=self._config.model,
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    async def chat_stream(self, request: ChatRequest) -> AsyncIterator[ChatResult]:
        started = time.perf_counter()
        text = ""
        stream = await self._get_client().chat.completions.create(
            **self._request_kwargs(request), stream=True
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            if chunk.choices[0].finish_reason == "content_filter":
                raise ContentBlockedError(self._name)
            piece = chunk.choices[0].delta.content
            if piece:
                text += piece
                yield ChatResult(
                    message=Message(role="assistant", content=text),
                    provider=self._name,
                    model=self._config.model,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )


register = make_register(
    name="openai",
    version="0.2.0",
    description="OpenAI AI provider",
    factory=OpenAIProvider,
)
