"""Tests for the ``run_async`` scheduling helper in ``panel_base``.

``QtWidgets`` is imported at module scope by ``panel_base``, so the
offscreen platform plugin is installed before import to guarantee the
import is safe on headless CI.
"""

from __future__ import annotations

import asyncio
import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from projectionai.ui.widgets.panel_base import _FOREGROUND_TASKS, run_async


def test_no_running_loop_falls_back_to_asyncio_run() -> None:
    """Synchronous fallback executes the coroutine to completion."""

    ran: list[bool] = []

    async def worker() -> None:
        ran.append(True)

    run_async(worker())

    assert ran == [True]


def test_running_loop_schedules_task_and_clears_set() -> None:
    """With a live loop the coroutine runs to completion and the done
    callback removes the task from the keep-alive set."""

    ran: list[bool] = []

    async def worker() -> None:
        await asyncio.sleep(0)
        ran.append(True)

    async def main() -> None:
        run_async(worker())
        await asyncio.sleep(0.05)

    asyncio.run(main())

    assert ran == [True]
    assert not _FOREGROUND_TASKS


def test_failed_task_is_logged_and_cleared(caplog: pytest.LogCaptureFixture) -> None:
    """A task that raises surfaces the exception on the module logger
    instead of being silently discarded."""

    async def boom() -> None:
        raise RuntimeError("kaboom")

    async def main() -> None:
        run_async(boom())
        await asyncio.sleep(0.05)

    with caplog.at_level(logging.WARNING, logger="projectionai.ui.widgets.panel_base"):
        asyncio.run(main())

    assert not _FOREGROUND_TASKS
    assert any(
        r.name == "projectionai.ui.widgets.panel_base"
        and r.levelno >= logging.WARNING
        and "Async panel task failed" in r.message
        and "kaboom" in r.message
        for r in caplog.records
    )
