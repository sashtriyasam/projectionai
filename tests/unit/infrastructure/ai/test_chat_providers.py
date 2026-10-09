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
from projectionai.services.ai import ChatRequest, ContentBlockedError, Message


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
        stop_reason="end_turn",
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text="Hel"),
            SimpleNamespace(type="text", text="lo"),
        ],
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
        choices=[
            SimpleNamespace(message=SimpleNamespace(content="ok"), finish_reason="stop")
        ]
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
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=None), finish_reason="stop")
        ]
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


async def _collect(stream: Any) -> list[str]:
    return [chunk.message.content async for chunk in stream]


async def test_anthropic_stream_yields_cumulative_text() -> None:
    class _Stream:
        text_stream = _aiter(["He", "llo"])

        async def __aenter__(self) -> _Stream:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def get_final_message(self) -> Any:
            return SimpleNamespace(stop_reason="end_turn")

    class _Messages:
        def stream(self, **_kwargs: Any) -> _Stream:
            return _Stream()

    client = SimpleNamespace(messages=_Messages())
    provider = AnthropicProvider(AnthropicConfig(api_key="k"), client=client)
    assert await _collect(provider.chat_stream(_request())) == ["He", "Hello"]


async def test_openai_stream_skips_empty_deltas() -> None:
    def _chunk(content: str | None, *, empty: bool = False) -> Any:
        choices = (
            []
            if empty
            else [
                SimpleNamespace(
                    delta=SimpleNamespace(content=content), finish_reason=None
                )
            ]
        )
        return SimpleNamespace(choices=choices)

    chunks = [_chunk("A"), _chunk(None), _chunk("", empty=True), _chunk("B")]

    class _Completions:
        async def create(self, **kwargs: Any) -> Any:
            assert kwargs["stream"] is True
            return _aiter(chunks)

    client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))
    provider = OpenAIProvider(OpenAIConfig(api_key="k"), client=client)
    assert await _collect(provider.chat_stream(_request())) == ["A", "AB"]


async def test_gemini_stream_yields_cumulative_text() -> None:
    chunks = [
        SimpleNamespace(text="Hi"),
        SimpleNamespace(text=None),
        SimpleNamespace(text=" there"),
    ]

    class _Models:
        async def generate_content_stream(self, **_kwargs: Any) -> Any:
            return _aiter(chunks)

    client = SimpleNamespace(aio=SimpleNamespace(models=_Models()))
    provider = GeminiProvider(GeminiConfig(api_key="k"), client=client)
    assert await _collect(provider.chat_stream(_request())) == ["Hi", "Hi there"]


async def _aiter(items: list[Any]) -> Any:
    for item in items:
        yield item


async def test_anthropic_refusal_raises_content_blocked() -> None:
    response = SimpleNamespace(content=[], stop_reason="refusal")
    client = SimpleNamespace(messages=_Recorder(response))
    provider = AnthropicProvider(AnthropicConfig(api_key="k"), client=client)
    with pytest.raises(ContentBlockedError):
        await provider.chat(_request())


async def test_openai_content_filter_raises_content_blocked() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=None), finish_reason="content_filter"
            )
        ]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=_Recorder(response)))
    provider = OpenAIProvider(OpenAIConfig(api_key="k"), client=client)
    with pytest.raises(ContentBlockedError):
        await provider.chat(_request())


async def test_gemini_blocked_prompt_raises_content_blocked() -> None:
    response = SimpleNamespace(
        text=None,
        prompt_feedback=SimpleNamespace(block_reason="SAFETY"),
    )
    client = SimpleNamespace(aio=SimpleNamespace(models=_Recorder(response)))
    provider = GeminiProvider(GeminiConfig(api_key="k"), client=client)
    with pytest.raises(ContentBlockedError):
        await provider.chat(_request())


def test_content_blocked_message_names_the_provider() -> None:
    from projectionai.services.ai import describe_provider_error

    message = describe_provider_error(ContentBlockedError("openai"), "OpenAI")
    assert "content policy" in message
    assert "OpenAI" in message
