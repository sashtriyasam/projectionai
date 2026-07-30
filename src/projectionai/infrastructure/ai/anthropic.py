"""Anthropic AI provider plugin."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from projectionai.core.config import AnthropicConfig
from projectionai.core.plugin import make_register
from projectionai.services.ai import (
    ChatRequest,
    ChatResult,
    GenerationRequest,
    GenerationResult,
)

_logger = logging.getLogger(__name__)


class AnthropicProvider:
    """AI provider using Anthropic's API."""

    def __init__(self, config: AnthropicConfig) -> None:
        self._config: AnthropicConfig = config
        self._name: str = "anthropic"

    @property
    def name(self) -> str:
        return self._name

    async def initialize(self) -> None:
        _logger.info("Anthropic provider initialized (model: %s)", self._config.model)

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
    name="anthropic",
    version="0.1.0",
    description="Anthropic AI provider",
    factory=AnthropicProvider,
)
