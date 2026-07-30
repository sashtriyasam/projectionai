"""Job manager — background job queue with progress and cancellation.

Manages asynchronous job execution in a background thread pool.
Supports queueing, progress reporting, cancellation, priority ordering,
and concurrency limits.
"""

from __future__ import annotations

import asyncio
import collections.abc
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any, override

from projectionai.core.events import (
    EventBus,
    JobCancelled,
    JobCompleted,
    JobFailed,
    JobProgress,
    JobQueued,
    JobStarted,
)
from projectionai.managers import Manager

_logger = logging.getLogger(__name__)


class JobPriority(int, Enum):
    """Priority levels for job queue ordering."""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class JobStatus(StrEnum):
    """Possible states for a job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class JobInfo:
    """Runtime information about a queued or running job."""

    job_id: str
    name: str
    status: JobStatus = JobStatus.PENDING
    priority: JobPriority = JobPriority.NORMAL
    progress: float = 0.0
    status_text: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    error: str | None = None
    result: Any = None
    fn: Callable[..., Any] | None = None
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    future: Future[Any] | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)


class JobManager(Manager):
    """Manages background job execution with a thread pool.

    Design:
    - Jobs run in a ``ThreadPoolExecutor`` so they never block the UI.
    - Maximum concurrency is configurable (default 4).
    - Jobs are ordered by priority (highest first), then FIFO within
      the same priority.
    - Cancellation sets an event that running jobs can check.
    """

    def __init__(
        self,
        event_bus: EventBus,
        max_concurrent: int = 4,
        queue_capacity: int = 100,
    ) -> None:
        super().__init__(event_bus)
        self._max_concurrent: int = max_concurrent
        self._queue_capacity: int = queue_capacity
        self._executor: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=max_concurrent,
            thread_name_prefix="job",
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread_id: int | None = None
        self._jobs: dict[str, JobInfo] = {}
        self._pending: list[str] = []  # ordered list of pending job IDs
        self._lock: threading.Lock = threading.Lock()
        self._is_shutting_down: bool = False

    # -- Properties ---------------------------------------------------------

    @property
    def pending_count(self) -> int:
        """Return the number of pending (queued) jobs."""
        with self._lock:
            return len(self._pending)

    @property
    def running_count(self) -> int:
        """Return the number of currently running jobs."""
        with self._lock:
            return sum(1 for j in self._jobs.values() if j.status == JobStatus.RUNNING)

    @property
    def job_count(self) -> int:
        """Return the total number of tracked jobs."""
        with self._lock:
            return len(self._jobs)

    def get_job(self, job_id: str) -> JobInfo | None:
        """Return the runtime info for a job, or ``None``."""
        with self._lock:
            return self._jobs.get(job_id)

    def get_jobs_by_status(self, status: JobStatus) -> list[JobInfo]:
        """Return all jobs with a given status."""
        with self._lock:
            return [j for j in self._jobs.values() if j.status == status]

    # -- Queue management ---------------------------------------------------

    def enqueue(
        self,
        job_id: str,
        name: str,
        fn: Any,
        priority: JobPriority = JobPriority.NORMAL,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> JobInfo:
        """Enqueue a job for background execution.

        Args:
            job_id: Unique identifier for the job.
            name: Human-readable job name.
            fn: Callable to execute (sync or async).
            priority: Priority level for queue ordering.
            args: Positional arguments for the callable.
            kwargs: Keyword arguments for the callable.

        Returns:
            The ``JobInfo`` instance for the queued job.

        Raises:
            ValueError: If a job with the same ID already exists.
            RuntimeError: If the queue is at capacity.
        """
        self._require_initialized()

        with self._lock:
            if job_id in self._jobs:
                raise ValueError(f"Job {job_id!r} already exists")

            if len(self._pending) >= self._queue_capacity:
                raise RuntimeError(f"Job queue is at capacity ({self._queue_capacity})")

            info = JobInfo(
                job_id=job_id,
                name=name,
                priority=priority,
                fn=fn,
                args=args,
                kwargs=kwargs if kwargs is not None else {},
            )
            self._jobs[job_id] = info
            self._pending.append(job_id)
            self._reorder_pending()

        _logger.debug("Enqueued job: %s (%s)", name, job_id)
        self._emit_nowait(JobQueued(job_id=job_id, job_type=name))

        # Try to dispatch immediately
        self._dispatch_next()

        return info

    def cancel(self, job_id: str) -> bool:
        """Cancel a pending or running job.

        Returns ``True`` if the job was successfully cancelled,
        ``False`` if not found or already completed.
        """
        with self._lock:
            info = self._jobs.get(job_id)
            if info is None:
                return False
            if info.status in (
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            ):
                return False

            # Signal cancellation
            info.cancel_event.set()

            # If pending, remove from queue
            if job_id in self._pending:
                self._pending.remove(job_id)
                info.status = JobStatus.CANCELLED
                info.completed_at = time.time()
                self._emit_nowait(JobCancelled(job_id=job_id))
                _logger.debug("Cancelled pending job: %s", job_id)
                return True

            # If running, mark as cancelled (thread will check the event)
            info.status = JobStatus.CANCELLED
            self._emit_nowait(JobCancelled(job_id=job_id))
            _logger.debug("Cancelled running job: %s", job_id)
            return True

    def cancel_all(self) -> int:
        """Cancel all pending and running jobs.

        Returns the number of jobs cancelled.
        """
        with self._lock:
            job_ids = list(self._jobs.keys())
        count = 0
        for job_id in job_ids:
            if self.cancel(job_id):
                count += 1
        return count

    # -- Progress reporting -------------------------------------------------

    def report_progress(
        self, job_id: str, progress: float, status_text: str = ""
    ) -> None:
        """Update progress for a running job.

        Called from within the job's execution function.
        """
        with self._lock:
            info = self._jobs.get(job_id)
            if info is None:
                return
            info.progress = progress
            info.status_text = status_text
        self._emit_nowait(
            JobProgress(job_id=job_id, progress=progress, status=status_text)
        )

    def should_cancel(self, job_id: str) -> bool:
        """Check whether a cancellation has been requested for a job.

        Called from within the job's execution function to poll for
        cancellation.
        """
        with self._lock:
            info = self._jobs.get(job_id)
            if info is None:
                return True
            return info.cancel_event.is_set()

    # -- Internal dispatch --------------------------------------------------

    def _dispatch_next(self) -> None:
        """Submit the next pending job to the executor if a slot is free."""
        with self._lock:
            if self._is_shutting_down:
                return
            running = sum(
                1 for j in self._jobs.values() if j.status == JobStatus.RUNNING
            )
            if running >= self._max_concurrent:
                return
            if not self._pending:
                return

            job_id = self._pending.pop(0)
            info = self._jobs[job_id]

            info.status = JobStatus.RUNNING
            info.started_at = time.time()

        self._emit_nowait(JobStarted(job_id=job_id))
        _logger.debug("Starting job: %s", info.name)

        info.future = self._executor.submit(self._run_job_wrapper, job_id, info)

    def _run_job_wrapper(self, job_id: str, info: JobInfo) -> None:
        """Execute a job's callable in the thread pool and handle completion."""
        try:
            if info.fn is None:
                raise ValueError(f"Job {job_id!r} has no callable")

            result = info.fn(*info.args, **info.kwargs)
            if isinstance(result, collections.abc.Coroutine):
                result = asyncio.run(result)
        except Exception as exc:
            self._complete_job(job_id, error=str(exc))
        else:
            self._complete_job(job_id, result=result)

    def _complete_job(
        self, job_id: str, result: Any = None, error: str | None = None
    ) -> None:
        """Mark a job as completed or failed and emit the appropriate event."""
        with self._lock:
            info = self._jobs.get(job_id)
            if info is None:
                return

            # If already cancelled by the cancel() path, don't overwrite
            if info.status == JobStatus.CANCELLED:
                return

            info.completed_at = time.time()
            event: JobFailed | JobCompleted
            if error:
                info.status = JobStatus.FAILED
                info.error = error
                event = JobFailed(job_id=job_id, reason=error)
                _logger.warning("Job failed: %s — %s", info.name, error)
            else:
                info.status = JobStatus.COMPLETED
                info.result = result
                event = JobCompleted(job_id=job_id)
                _logger.debug("Job completed: %s", info.name)

            # Emit while holding the lock so the event is scheduled before
            # other threads observe the terminal status
            self._emit_nowait(event)

        # Dispatch the next waiting job
        self._dispatch_next()

    def _reorder_pending(self) -> None:
        """Sort pending jobs by priority (highest first)."""
        self._pending.sort(
            key=lambda jid: (
                -self._jobs[jid].priority.value if jid in self._jobs else 0,
                self._jobs[jid].created_at if jid in self._jobs else 0,
            )
        )

    # -- Internal -----------------------------------------------------------

    @override
    def _emit_nowait(self, event: Any) -> None:
        """Emit an event without awaiting (fire-and-forget).

        Uses ``create_task`` when called from the loop's owning thread and
        ``run_coroutine_threadsafe`` from worker threads so events are
        never silently dropped.
        """
        loop = self._loop
        if loop is None:
            _logger.warning(
                "No event loop captured — dropping event: %s", type(event).__name__
            )
            return
        if threading.get_ident() == self._loop_thread_id:
            task = loop.create_task(self._event_bus.emit(event))
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
        else:
            _ = asyncio.run_coroutine_threadsafe(self._event_bus.emit(event), loop)

    # -- Lifecycle ----------------------------------------------------------

    @override
    async def _on_initialize(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._loop_thread_id = threading.get_ident()
        _logger.debug(
            "JobManager initialized (max_concurrent=%d, capacity=%d)",
            self._max_concurrent,
            self._queue_capacity,
        )

    @override
    async def _on_shutdown(self) -> None:
        with self._lock:
            self._is_shutting_down = True
        _ = self.cancel_all()
        await asyncio.to_thread(lambda: self._executor.shutdown(wait=True))
        with self._lock:
            self._jobs.clear()
            self._pending.clear()
