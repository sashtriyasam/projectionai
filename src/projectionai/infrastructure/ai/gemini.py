"""Gemini AI provider plugin."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from projectionai.core.config import GeminiConfig
from projectionai.core.plugin import make_register
from projectionai.services.ai import (
    ChatRequest,
    ChatResult,
    GenerationRequest,
    GenerationResult,
)

_logger = logging.getLogger(__name__)


class GeminiProvider:
    """AI provider using Google's Gemini API."""

    def __init__(self, config: GeminiConfig) -> None:
        self._config: GeminiConfig = config
        self._name: str = "gemini"

    @property
    def name(self) -> str:
        return self._name

    async def initialize(self) -> None:
        _logger.info("Gemini provider initialized (model: %s)", self._config.model)

    async def shutdown(self) -> None: ...

    async def generate(self, _request: GenerationRequest) -> GenerationResult:
        raise NotImplementedError

    async def generate_stream(
        self,
        _request: GenerationRequest,
    ) -> AsyncIterator[GenerationResult]:
        raise NotImplementedError
        # pyright: ignore[reportUnreachable] — unreachable; keeps this an async generator
        yield

    async def chat(self, _request: ChatRequest) -> ChatResult:
        raise NotImplementedError

    async def chat_stream(
        self,
        _request: ChatRequest,
    ) -> AsyncIterator[ChatResult]:
        raise NotImplementedError
        # pyright: ignore[reportUnreachable] — unreachable; keeps this an async generator
        yield


register = make_register(
    name="gemini",
    version="0.1.0",
    description="Google Gemini AI provider",
    factory=GeminiProvider,
)
