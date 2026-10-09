"""Chat behaviour of the Anthropic, OpenAI and Gemini providers.

Clients are replaced with recording fakes so no network calls are made.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from projectionai.core.config import AnthropicConfig, GeminiConfig, OpenAIConfig
from projectionai.infrastructure.ai.anthropic import AnthropicProvider
from projectionai.infrastructure.ai.gemini import GeminiProvider
from projectionai.infrastructure.ai.openai_provider import OpenAIProvider
from projectionai.services.ai import ChatRequest, Message


class _Recorder:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self.response

    async def generate_content(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self.response


def _request(system: str | None = None) -> ChatRequest:
    return ChatRequest(
        messages=(Message("user", "hi"), Message("assistant", "hello")),
        system_prompt=system,
        max_tokens=256,
    )


async def test_anthropic_chat_joins_text_blocks_and_omits_temperature() -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text="Hel"),
            SimpleNamespace(type="text", text="lo"),
        ]
    )
    recorder = _Recorder(response)
    client = SimpleNamespace(messages=recorder)
    provider = AnthropicProvider(AnthropicConfig(api_key="k"), client=client)

    result = await provider.chat(_request(system="be brief"))

    assert result.message == Message("assistant", "Hello")
    assert result.provider == "anthropic"
    assert "temperature" not in recorder.kwargs
    assert recorder.kwargs["system"] == "be brief"
    assert recorder.kwargs["max_tokens"] == 256


async def test_openai_chat_puts_system_prompt_first() -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
    )
    recorder = _Recorder(response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=recorder))
    provider = OpenAIProvider(OpenAIConfig(api_key="k"), client=client)

    result = await provider.chat(_request(system="be brief"))

    assert result.message.content == "ok"
    assert recorder.kwargs["messages"][0] == {
        "role": "system",
        "content": "be brief",
    }
    assert recorder.kwargs["max_completion_tokens"] == 256
    assert "temperature" not in recorder.kwargs


async def test_openai_null_content_becomes_empty_string() -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=_Recorder(response)))
    provider = OpenAIProvider(OpenAIConfig(api_key="k"), client=client)
    assert (await provider.chat(_request())).message.content == ""


async def test_gemini_maps_assistant_role_to_model() -> None:
    recorder = _Recorder(SimpleNamespace(text="hey"))
    client = SimpleNamespace(aio=SimpleNamespace(models=recorder))
    provider = GeminiProvider(GeminiConfig(api_key="k"), client=client)

    result = await provider.chat(_request(system="be brief"))

    assert result.message.content == "hey"
    roles = [c["role"] for c in recorder.kwargs["contents"]]
    assert roles == ["user", "model"]
    assert recorder.kwargs["config"]["system_instruction"] == "be brief"


@pytest.mark.parametrize(
    ("provider_cls", "config"),
    [
        (AnthropicProvider, AnthropicConfig(api_key="")),
        (OpenAIProvider, OpenAIConfig(api_key="")),
        (GeminiProvider, GeminiConfig(api_key="")),
    ],
)
async def test_missing_key_fails_initialize(provider_cls: Any, config: Any) -> None:
    with pytest.raises(RuntimeError, match="is not set"):
        await provider_cls(config).initialize()
