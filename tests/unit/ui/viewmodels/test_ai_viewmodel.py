"""Tests for AiViewModel busy/error state."""

from __future__ import annotations

import asyncio
from typing import Any

from projectionai.services.ai import ChatResult, Message
from projectionai.ui.viewmodels.ai import AiViewModel


class _Provider:
    name = "fake"


class _FakeService:
    def __init__(self, *, error: BaseException | None = None) -> None:
        self.provider = _Provider()
        self._error = error
        self.calls = 0
        self.gate = asyncio.Event()
        self.gate.set()

    async def chat(self, request: Any) -> ChatResult:
        self.calls += 1
        await self.gate.wait()
        if self._error is not None:
            raise self._error
        return ChatResult(
            message=Message(role="assistant", content="ok"),
            provider="fake",
            model="fake-model",
        )


async def test_chat_success_clears_busy_and_error() -> None:
    vm = AiViewModel(_FakeService())  # type: ignore[arg-type]
    assert await vm.chat("hi") == "ok"
    assert not vm.busy
    assert vm.last_error == ""
    assert [m.role for m in vm.transcript()] == ["user", "assistant"]


async def test_chat_failure_sets_user_facing_error() -> None:
    vm = AiViewModel(_FakeService(error=RuntimeError("boom")))  # type: ignore[arg-type]
    assert await vm.chat("hi") is None
    assert not vm.busy
    assert vm.last_error


async def test_unimplemented_provider_reports_unsupported() -> None:
    vm = AiViewModel(_FakeService(error=NotImplementedError()))  # type: ignore[arg-type]
    assert await vm.chat("hi") is None
    assert "does not support chat" in vm.last_error


async def test_concurrent_send_is_ignored_while_busy() -> None:
    service = _FakeService()
    service.gate.clear()
    vm = AiViewModel(service)  # type: ignore[arg-type]
    first = asyncio.ensure_future(vm.chat("one"))
    await asyncio.sleep(0)
    assert vm.busy
    assert await vm.chat("two") is None
    service.gate.set()
    assert await first == "ok"
    assert service.calls == 1
