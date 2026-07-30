"""AI provider abstraction.

Every AI provider implements this interface. The application never
imports a specific provider — it requests one by name from the
plugin registry and uses the interface.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Message:
    """A single message in a conversation."""

    role: str  # "user" | "assistant" | "system"
    content: str


@dataclass(frozen=True)
class GenerationRequest:
    """Parameters for a content generation request."""

    prompt: str
    system_prompt: str | None = None
    image_paths: tuple[str, ...] = ()
    width: int = 1024
    height: int = 1024
    num_images: int = 1
    temperature: float = 0.8
    extra: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationResult:
    """Result of a content generation request."""

    images: tuple[str, ...] = ()  # Paths to generated image files
    text: str | None = None  # Text response (if text-generation model)
    provider: str = ""  # Provider name (for logging/diagnostics)
    model: str = ""  # Model name used
    latency_ms: float = 0.0  # Wall-clock time


@dataclass(frozen=True)
class ChatRequest:
    """Parameters for a chat completion request."""

    messages: tuple[Message, ...]
    system_prompt: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096


@dataclass(frozen=True)
class ChatResult:
    """Result of a chat completion request."""

    message: Message
    provider: str
    model: str
    latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------


class AIProvider(Protocol):
    """Interface that every AI provider plugin must satisfy."""

    @property
    def name(self) -> str:
        """Unique provider identifier (e.g. ``"gemini"``, ``"openai"``)."""
        ...

    async def initialize(self) -> None:
        """Initialize the provider (e.g., validate credentials, warm up)."""
        ...

    async def shutdown(self) -> None:
        """Release provider resources."""
        ...

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Generate media content from a text/image prompt.

        Returns paths to generated files on disk.
        """
        ...

    async def chat(self, request: ChatRequest) -> ChatResult:
        """Send a chat message and get a response."""
        ...

    async def generate_stream(
        self, _request: GenerationRequest
    ) -> AsyncIterator[GenerationResult]:
        """Stream partial generation results.

        The final result in the stream carries the complete output.
        """
        if False:  # kept unreachable to make this an async generator
            yield

    async def chat_stream(self, _request: ChatRequest) -> AsyncIterator[ChatResult]:
        """Stream a chat response token by token."""
        if False:  # kept unreachable to make this an async generator
            yield


# ---------------------------------------------------------------------------
# AI Service — wraps a provider with lifecycle management
# ---------------------------------------------------------------------------


class AIService:
    """High-level AI service that manages the active provider.

    Usage::

        service = AIService(registry, "gemini")
        await service.initialize()
        result = await service.generate(GenerationRequest(prompt="..."))
        await service.shutdown()
    """

    def __init__(self, provider: AIProvider) -> None:
        self._provider: AIProvider = provider

    @property
    def provider(self) -> AIProvider:
        """Return the active provider instance."""
        return self._provider

    async def initialize(self) -> None:
        """Initialize the underlying provider."""
        await self._provider.initialize()

    async def shutdown(self) -> None:
        """Shut down the underlying provider."""
        await self._provider.shutdown()

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Delegate to the active provider."""
        return await self._provider.generate(request)

    async def generate_stream(
        self, request: GenerationRequest
    ) -> AsyncIterator[GenerationResult]:
        """Delegate streaming to the active provider."""
        async for chunk in self._provider.generate_stream(request):
            yield chunk

    async def chat(self, request: ChatRequest) -> ChatResult:
        """Delegate chat to the active provider."""
        return await self._provider.chat(request)

    async def chat_stream(self, request: ChatRequest) -> AsyncIterator[ChatResult]:
        """Delegate streaming chat to the active provider."""
        async for chunk in self._provider.chat_stream(request):
            yield chunk
