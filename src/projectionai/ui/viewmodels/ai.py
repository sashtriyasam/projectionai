"""AiViewModel — AI Assistant chat and generation.

Qt-free. Wraps an optional :class:`AIService` (``None`` when no
provider plugin is loaded — the panel then renders a disabled state).
Keeps a local transcript of chat messages; generation requests return
``None`` when the service is unavailable or fails.
"""

from __future__ import annotations

import logging
from pathlib import Path

from projectionai.services.ai import (
    AIService,
    ChatRequest,
    GenerationRequest,
    GenerationResult,
    Message,
)
from projectionai.ui.viewmodels.observable import Observable

_logger = logging.getLogger(__name__)


class AiViewModel(Observable):
    """Observable AI-assistant facade."""

    def __init__(self, ai_service: AIService | None = None) -> None:
        super().__init__()
        self._ai = ai_service
        self._transcript: list[Message] = []

    # -- State ----------------------------------------------------------------

    @property
    def available(self) -> bool:
        """True when an AI provider service is attached."""
        return self._ai is not None

    @property
    def provider_name(self) -> str:
        """Name of the active provider (``""`` when unavailable)."""
        if self._ai is None:
            return ""
        return self._ai.provider.name

    # -- Chat transcript --------------------------------------------------------

    def transcript(self) -> list[Message]:
        """Chat messages in display order (oldest first)."""
        return list(self._transcript)

    def clear_transcript(self) -> None:
        """Clear the local chat transcript."""
        self._transcript.clear()
        self._notify()

    # -- Operations ---------------------------------------------------------------

    async def chat(self, text: str) -> str | None:
        """Send a chat message; returns the assistant reply or ``None``.

        The user message is always recorded; the reply is appended when
        the provider responds.
        """
        if self._ai is None:
            return None
        self._transcript.append(Message(role="user", content=text))
        self._notify()
        request = ChatRequest(messages=tuple(self._transcript))
        try:
            result = await self._ai.chat(request)
        except Exception:
            _logger.exception("AI chat request failed")
            return None
        reply = result.message.content
        self._transcript.append(Message(role=result.message.role, content=reply))
        self._notify()
        return reply

    async def generate(self, prompt: str) -> GenerationResult | None:
        """Generate media from *prompt*; returns the result or ``None``.

        The generation prompt is recorded in the transcript as a user
        message when a service is attached.
        """
        if self._ai is None:
            return None
        self._transcript.append(Message(role="user", content=prompt))
        self._notify()
        request = GenerationRequest(prompt=prompt)
        try:
            result = await self._ai.generate(request)
        except Exception:
            _logger.exception("AI generation request failed")
            return None
        if result.images:
            content = ", ".join(Path(p).name for p in result.images)
        elif result.text:
            content = result.text[:120]
        else:
            content = f"Generated media ({result.provider})"
        self._transcript.append(Message(role="assistant", content=content))
        self._notify()
        return result
