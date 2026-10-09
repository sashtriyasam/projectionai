"""Gemini AI provider plugin (chat via the ``google-genai`` SDK)."""

from __future__ import annotations

import importlib.util
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from projectionai.core.config import GeminiConfig
from projectionai.core.plugin import make_register
from projectionai.services.ai import (
    ChatRequest,
    ChatResult,
    GenerationRequest,
    GenerationResult,
    Message,
)

_logger = logging.getLogger(__name__)


class GeminiProvider:
    """AI provider using Google's Gemini ``generate_content`` API."""

    def __init__(self, config: GeminiConfig, client: Any | None = None) -> None:
        self._config: GeminiConfig = config
        self._name: str = "gemini"
        self._client: Any | None = client

    @property
    def name(self) -> str:
        return self._name

    async def initialize(self) -> None:
        if importlib.util.find_spec("google.genai") is None:
            raise RuntimeError(
                "Gemini provider needs the 'google-genai' package "
                "(pip install 'projectionai[gemini]')."
            )
        if not self._config.api_key:
            raise RuntimeError("GEMINI_API_KEY is not set.")
        _logger.info("Gemini provider initialized (model: %s)", self._config.model)

    async def shutdown(self) -> None:
        self._client = None

    def _get_client(self) -> Any:
        if self._client is None:
            import google.genai as genai

            self._client = genai.Client(api_key=self._config.api_key)
        return self._client

    async def generate(self, _request: GenerationRequest) -> GenerationResult:
        raise NotImplementedError("Gemini image generation is not implemented yet.")

    async def generate_stream(
        self,
        _request: GenerationRequest,
    ) -> AsyncIterator[GenerationResult]:
        raise NotImplementedError("Gemini image generation is not implemented yet.")
        # pyright: ignore[reportUnreachable] — unreachable; keeps this an async generator
        yield

    async def chat(self, request: ChatRequest) -> ChatResult:
        contents = [
            {
                # Gemini calls the assistant role "model".
                "role": "model" if m.role == "assistant" else "user",
                "parts": [{"text": m.content}],
            }
            for m in request.messages
            if m.role in ("user", "assistant")
        ]
        config: dict[str, Any] = {
            "max_output_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.system_prompt:
            config["system_instruction"] = request.system_prompt

        started = time.perf_counter()
        response = await self._get_client().aio.models.generate_content(
            model=self._config.model,
            contents=contents,
            config=config,
        )
        return ChatResult(
            message=Message(role="assistant", content=response.text or ""),
            provider=self._name,
            model=self._config.model,
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    async def chat_stream(self, _request: ChatRequest) -> AsyncIterator[ChatResult]:
        raise NotImplementedError("Streaming chat is not implemented yet.")
        # pyright: ignore[reportUnreachable] — unreachable; keeps this an async generator
        yield


register = make_register(
    name="gemini",
    version="0.2.0",
    description="Google Gemini AI provider",
    factory=GeminiProvider,
)
