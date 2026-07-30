"""OpenAI AI provider plugin."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from projectionai.core.config import OpenAIConfig
from projectionai.core.plugin import make_register
from projectionai.services.ai import (
    ChatRequest,
    ChatResult,
    GenerationRequest,
    GenerationResult,
)

_logger = logging.getLogger(__name__)


class OpenAIProvider:
    """AI provider using OpenAI's API."""

    def __init__(self, config: OpenAIConfig) -> None:
        self._config: OpenAIConfig = config
        self._name: str = "openai"

    @property
    def name(self) -> str:
        return self._name

    async def initialize(self) -> None:
        _logger.info("OpenAI provider initialized (model: %s)", self._config.model)

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
    name="openai",
    version="0.1.0",
    description="OpenAI AI provider",
    factory=OpenAIProvider,
)
