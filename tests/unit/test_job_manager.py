"""Tests for JobManager."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from projectionai.core.events import (
    JobCancelled,
    JobCompleted,
    JobFailed,
    JobProgress,
    JobQueued,
    JobStarted,
)
from projectionai.managers.job_manager import JobManager, JobPriority, JobStatus


def _simple_fn(result: str = "done") -> str:
    """A simple synchronous job function."""
    return result


def _slow_fn(duration: float = 0.05) -> str:
    """A job that simulates work by sleeping."""
    time.sleep(duration)
    return "slow_done"


def _blocking_fn(event: threading.Event) -> str:
    """Block until ``event`` is set (keeps a worker slot occupied)."""
    event.wait()
    return "unblocked"


def _failing_fn() -> str:
    """A job that always fails."""
    msg = "Something went wrong"
    raise RuntimeError(msg)


@pytest.fixture
async def manager(event_bus):
    m = JobManager(event_bus, max_concurrent=2, queue_capacity=50)
    await m.initialize()
    try:
        yield m
    finally:
        await m.shutdown()


class TestJobManagerQueue:
    """Enqueue, dispatch, and basic lifecycle."""

    async def test_enqueue(self, manager: JobManager) -> None:
        # Fill executor slots so the new job stays in _pending
        for i in range(manager._max_concurrent):
            manager.enqueue(f"filler{i}", f"Filler{i}", _slow_fn, args=(0.2,))
        info = manager.enqueue("job1", "Test Job", _slow_fn, args=(0.2,))

        assert info.job_id == "job1"
        assert info.name == "Test Job"
        assert info.status == JobStatus.PENDING
        assert manager.job_count == 3
        assert manager.pending_count == 1

    async def test_enqueue_emits_event(self, manager: JobManager, event_bus) -> None:
        manager.enqueue("j1", "Test", _simple_fn)
        await asyncio.sleep(0)
        event_bus.assert_event_emitted(JobQueued)

    async def test_enqueue_duplicate_id_raises(self, manager: JobManager) -> None:
        manager.enqueue("j1", "First", _simple_fn)
        with pytest.raises(ValueError, match="already exists"):
            manager.enqueue("j1", "Duplicate", _simple_fn)

    async def test_enqueue_queue_full_raises(self, event_bus) -> None:
        tiny = JobManager(event_bus, max_concurrent=1, queue_capacity=1)
        await tiny.initialize()
        try:
            tiny.enqueue("j1", "First", _slow_fn, args=(0.2,))  # dispatched to executor
            tiny.enqueue("j2", "Second", _slow_fn, args=(0.2,))  # stays in _pending
            with pytest.raises(RuntimeError, match="at capacity"):
                tiny.enqueue("j3", "Third", _simple_fn)  # _pending is full
        finally:
            await tiny.shutdown()

    async def test_get_job(self, manager: JobManager) -> None:
        manager.enqueue("j1", "GetMe", _simple_fn)
        info = manager.get_job("j1")
        assert info is not None
        assert info.name == "GetMe"

    async def test_get_job_not_found(self, manager: JobManager) -> None:
        assert manager.get_job("nonexistent") is None

    async def test_get_jobs_by_status(self, manager: JobManager) -> None:
        # Fill executor slots so these jobs stay in _pending
        for i in range(manager._max_concurrent):
            manager.enqueue(f"filler{i}", f"Filler{i}", _slow_fn, args=(0.2,))
        manager.enqueue("j1", "Alpha", _simple_fn)
        manager.enqueue("j2", "Beta", _simple_fn)

        pending = manager.get_jobs_by_status(JobStatus.PENDING)
        assert len(pending) == 2

    async def test_list_jobs_returns_snapshot(self, manager: JobManager) -> None:
        # Fill executor slots so jobs stay in _pending
        for i in range(manager._max_concurrent):
            manager.enqueue(f"filler{i}", f"Filler{i}", _slow_fn, args=(0.2,))
        manager.enqueue("j1", "Alpha", _simple_fn)
        manager.enqueue("j2", "Beta", _simple_fn)

        snapshot = manager.list_jobs()
        assert {j.job_id for j in snapshot} == {"filler0", "filler1", "j1", "j2"}
        # The snapshot is a fresh list: mutating it does not touch the manager
        snapshot.pop()
        assert manager.job_count == 4


class TestJobManagerCompletion:
    """Job completion, failure, and events."""

    async def test_job_completes_successfully(
        self, manager: JobManager, event_bus
    ) -> None:
        manager.enqueue("j1", "Quick", _simple_fn, args=("ok",))
        # Give it a moment to execute
        await self._wait_for_job(manager, "j1")

        info = manager.get_job("j1")
        assert info is not None
        assert info.status == JobStatus.COMPLETED
        await asyncio.sleep(0)
        event_bus.assert_event_emitted(JobCompleted)

    async def test_job_failure(self, manager: JobManager, event_bus) -> None:
        manager.enqueue("j_fail", "Failing", _failing_fn)
        await self._wait_for_job(manager, "j_fail")

        info = manager.get_job("j_fail")
        assert info is not None
        assert info.status == JobStatus.FAILED
        await asyncio.sleep(0)
        event_bus.assert_event_emitted(JobFailed)

    async def test_job_timing(self, manager: JobManager) -> None:
        manager.enqueue("j_t", "Timed", _slow_fn, args=(0.05,))
        await self._wait_for_job(manager, "j_t")

        info = manager.get_job("j_t")
        assert info is not None
        assert info.started_at is not None
        assert info.completed_at is not None
        assert info.completed_at > info.started_at

    async def test_emit_job_started(self, manager: JobManager, event_bus) -> None:
        manager.enqueue("j_ev", "Eventful", _simple_fn)
        await self._wait_for_job(manager, "j_ev")
        await asyncio.sleep(0)
        event_bus.assert_event_emitted(JobStarted)

    @staticmethod
    async def _wait_for_job(
        manager: JobManager, job_id: str, timeout: float = 2.0
    ) -> None:
        """Spin-wait until the job reaches a terminal state.

        Uses ``await asyncio.sleep`` so the event loop processes
        ``run_coroutine_threadsafe`` callbacks from background threads
        during the wait.

        The initial ``sleep(0)`` is critical: if the job finished
        *before* this method runs, the ``run_coroutine_threadsafe``
        callback is already in the loop's ``_ready`` deque but the
        scheduled task it creates won't execute until a second
        ``_run_once`` cycle completes.
        """
        await asyncio.sleep(0)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            info = manager.get_job(job_id)
            if info is not None and info.status in (
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            ):
                return
            await asyncio.sleep(0.01)
        pytest.fail(f"Job {job_id} did not complete within {timeout}s")


class TestJobManagerCancellation:
    """Job cancellation."""

    async def test_cancel_pending_job(self, manager: JobManager, event_bus) -> None:
        # Fill the executor so our target stays pending
        manager.enqueue("filler1", "Filler", _slow_fn, args=(0.2,))
        manager.enqueue("filler2", "Filler", _slow_fn, args=(0.2,))
        manager.enqueue("target", "Target", _simple_fn)

        result = manager.cancel("target")
        assert result

        info = manager.get_job("target")
        assert info is not None
        assert info.status == JobStatus.CANCELLED
        await asyncio.sleep(0)
        event_bus.assert_event_emitted(JobCancelled)

    async def test_cancel_nonexistent(self, manager: JobManager) -> None:
        assert not manager.cancel("ghost")

    async def test_cancel_completed_job(self, manager: JobManager) -> None:
        manager.enqueue("fin", "Finish", _simple_fn)
        await self._wait_for_job(manager, "fin")

        assert not manager.cancel("fin")

    @staticmethod
    async def _wait_for_job(
        manager: JobManager, job_id: str, timeout: float = 2.0
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            info = manager.get_job(job_id)
            if info is not None and info.status in (
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            ):
                return
            await asyncio.sleep(0.01)
        pytest.fail(f"Job {job_id} did not complete within {timeout}s")


class TestJobManagerProgress:
    """Progress reporting."""

    async def test_report_progress(self, manager: JobManager) -> None:
        manager.enqueue("jp", "Progress", _simple_fn)
        manager.report_progress("jp", 0.5, "Halfway")

        info = manager.get_job("jp")
        assert info is not None
        assert info.progress == 0.5
        assert info.status_text == "Halfway"

    async def test_report_progress_emits(self, manager: JobManager, event_bus) -> None:
        manager.enqueue("jp2", "Progress", _simple_fn)
        manager.report_progress("jp2", 0.75, "Three quarters")
        await asyncio.sleep(0)
        event_bus.assert_event_emitted(JobProgress)

    async def test_report_progress_unknown_job(self, manager: JobManager) -> None:
        manager.report_progress("ghost", 0.5)  # should not raise


class TestJobManagerPriority:
    """Priority ordering."""

    async def test_priority_ordering(self, manager: JobManager) -> None:
        # Occupy both worker slots with blocking jobs so priority
        # jobs stay in _pending — the fillers remain running until
        # released after the assertion, avoiding a race.
        barriers = [threading.Event() for _ in range(manager._max_concurrent)]
        for i, barrier in enumerate(barriers):
            manager.enqueue(
                f"filler{i}",
                f"Filler{i}",
                _blocking_fn,
                args=(barrier,),
            )
        manager.enqueue("low", "Low", _simple_fn, priority=JobPriority.LOW)
        manager.enqueue("high", "High", _simple_fn, priority=JobPriority.HIGH)
        manager.enqueue("crit", "Critical", _simple_fn, priority=JobPriority.CRITICAL)

        # Pending queue should be sorted: critical, high, low
        with manager._lock:
            assert manager._pending == ["crit", "high", "low"]

        # Release filler workers so the test can tear down cleanly
        for barrier in barriers:
            barrier.set()


class TestJobManagerCancelAll:
    """Cancel all jobs."""

    async def test_cancel_all(self, manager: JobManager) -> None:
        for i in range(5):
            manager.enqueue(f"j{i}", f"Job {i}", _slow_fn, args=(0.2,))

        count = manager.cancel_all()
        assert count == 5
        assert manager.job_count == 5  # still tracked
        assert manager.pending_count == 0
